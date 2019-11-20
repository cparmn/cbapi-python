import logging
from threatintel import ThreatIntel
from cabby.exceptions import NoURIProvidedError, ClientException
from cabby import create_client
from dataclasses import dataclass, field
import yaml
import os
from stix_parse import parse_stix, BINDING_CHOICES
from feed_helper import FeedHelper
from datetime import datetime
from results import IOC_v2, AnalysisResult
import urllib3

logging.basicConfig(level=logging.INFO)

handled_exceptions = (NoURIProvidedError, ClientException)


def load_config_from_file():
    logging.debug("loading config from file")
    config_filename = os.path.join(os.path.dirname((os.path.abspath(__file__))), "config.yml")
    with open(config_filename, "r") as config_file:
        config_data = yaml.load(config_file, Loader=yaml.SafeLoader)
        logging.info(f"loaded config data: {config_data}")
        return config_data


@dataclass(eq=True, frozen=True)
class TaxiiSiteConfig:
    feed_id: str = ''
    site: str = ''
    discovery_path: str = ''
    collection_management_path: str = ''
    poll_path: str = ''
    use_https: bool = False
    ssl_verify: bool = False
    cert_file: str = None
    key_file: str = None
    default_score: int = 5  # [1,10]
    username: str = None
    password: str = None
    collections: str = '*'
    start_date: str = '2019-01-01 00:00:00'
    minutes_to_advance: int = 60
    ca_cert: str = None
    http_proxy_url: str = None
    https_proxy_url: str = None
    reports_limit: int = 10000
    fail_limit: int = 10   # num attempts per collection for polling & parsing


class TaxiiSiteConnector():
    def __init__(self, site_conf):
        self.config = TaxiiSiteConfig(**site_conf)
        self.client = None

    def create_taxii_client(self):
        conf = self.config
        if not conf.ssl_verify:
            urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
        try:
            client = create_client(conf.site,
                                   use_https=conf.use_https,
                                   discovery_path=conf.discovery_path)
            client.set_auth(username=conf.username,
                            password=conf.password,
                            verify_ssl=conf.ssl_verify,
                            ca_cert=conf.ca_cert,
                            cert_file=conf.cert_file,
                            key_file=conf.key_file)

            proxy_dict = dict()
            if conf.http_proxy_url:
                proxy_dict['http'] = conf.http_proxy_url
            if conf.https_proxy_url:
                proxy_dict['https'] = conf.https_proxy_url
            if proxy_dict:
                client.set_proxies(proxy_dict)

            self.client = client

        except handled_exceptions as e:
            logging.error(f"Error creating client: {e}")



    def create_uri(self, config_path):
        uri = None
        if self.config.site and config_path:
            if self.config.use_https:
                uri = 'https://'
            else:
                uri = 'http://'
            uri = uri + self.config.site + config_path
        return uri



    def query_collections(self):
        collections = []
        try:
            uri = self.create_uri(self.config.collection_management_path)
            collections = self.client.get_collections(
                uri=uri)  # autodetect if uri=None
            for collection in collections:
                logging.debug(f"Collection: {collection.name}, {collection.type}")
        except handled_exceptions as e:
            logging.warning(f"Problem fetching collections from taxii server: {e}")
        return collections

    def poll_server(self, collection, feed_helper):
        content_blocks = []
        uri = self.create_uri(self.config.poll_path)
        try:
            logging.info(f"Polling Collection: {collection.name}")
            content_blocks = self.client.poll(
                uri=uri,
                collection_name=collection.name,
                begin_date=feed_helper.start_date,
                end_date=feed_helper.end_date,
                content_bindings=BINDING_CHOICES)
        except handled_exceptions as e:
            logging.warning(f"problem polling taxii server: {e}")
        return content_blocks

    def parse_collection_content(self, content_blocks):
        for block in content_blocks:
            yield from parse_stix(block.content, self.config.default_score)

    def import_collection(self, collection):
        num_times_empty_content_blocks = 0
        advance = True
        reports_limit = self.config.reports_limit
        logging.info(f"reports limit: {reports_limit}")
        feed_helper = FeedHelper(self.config.start_date,
                                 self.config.minutes_to_advance)

        while feed_helper.advance():
            num_reports = 0
            content_blocks = self.poll_server(collection, feed_helper)
            reports = self.parse_collection_content(content_blocks)
            for report in reports:
                yield report
                num_reports += 1
                if num_reports > reports_limit:
                    logging.info(f"Reports limit of {reports_limit} reached")
                    advance = False
                    break

            if not advance:
                break
            if collection.type == 'DATA_SET':  # data is unordered, not a feed
                logging.info(f"collection:{collection}; type data_set; breaking")
                break
            if num_reports == 0:
                num_times_empty_content_blocks += 1
            if num_times_empty_content_blocks > self.config.fail_limit:
                logging.error('Max fail limit reached; Exiting.')
                break
            reports_limit -= num_reports

    def import_collections(self, available_collections):
        desired_collections = self.config.collections
        desired_collections = [x.strip()
                               for x in desired_collections.lower().split(',')]

        want_all = False
        if '*' in desired_collections:
            want_all = True

        for collection in available_collections:
            if collection.type != 'DATA_FEED' and collection.type != 'DATA_SET':
                logging.debug(f"collection:{collection}; type not feed or data")
                continue
            if not collection.available:
                logging.debug(f"collection:{collection} not available")
                continue
            if want_all or collection.name.lower() in desired_collections:
                yield from self.import_collection(collection)

    def generate_reports(self):   # NOTE:ignoring binary for now
        reports = []

        self.create_taxii_client()
        if not self.client:
            logging.error('Unable to create taxii client.  Exiting...')
            return reports

        available_collections = self.query_collections()
        if not available_collections:
            logging.warning('Unable to find any collections.  Exiting...')
            return reports

        reports = self.import_collections(available_collections)
        if not reports:
            logging.warning('Unable to import collections.  Exiting...')
            return reports

        return reports




class StixTaxii():
    def __init__(self, site_confs):
        self.config = site_confs
        self.client = None

    def result(self, **kwargs):
        """
        Returns a new AnalysisResult with the given fields populated, updating
        the database in the background.

        This should be used within the :meth:`analyze` method to create
        analysis results.

        :rtype: :class:`AnalysisResult`

        Example::

        >>> self.result(analysis_name="foo", score=10)
        """

        result = AnalysisResult(**kwargs).normalize()
        return result


    def configure_sites(self):
        self.sites = {}
        try:
            for site_name, site_conf in self.config['sites'].items():
                self.sites[site_name] = TaxiiSiteConnector(site_conf)
                logging.info(f"loaded site {site_name}")
        except handled_exceptions as e:

            logging.error(f"Error in parsing config file: {e}")

    def format_report(self, reports):
        for report in reports:
            try:
                analysis_name = report['id']
                title = report['title']
                description = report['description']
                scan_time = datetime.fromtimestamp(report['timestamp'])
                score = report['score']
                link = report['link']
                ioc_dict = report['iocs_v2']
                result = self.result(
                                     analysis_name=analysis_name,
                                     scan_time=scan_time,
                                     score=score,
                                     title=title,
                                     description=description)
                for ioc_key, ioc_val in ioc_dict.items():
                    result.attach_ioc_v2(values=ioc_val, field=ioc_key, link=link)
            except handled_exceptions as e:
                logging.warning(f"Problem in report formatting: {e}")
                result = self.result(
                    analysis_name="exception_format_report", error=True)
            yield result

    def analyze(self):
        self.configure_sites()
        ti = ThreatIntel()
        for site_name, site_conn in self.sites.items():
            logging.info(f"Talking to {site_name} server")
            reports = site_conn.generate_reports()
            if not reports:
                yield self.result(
                    analysis_name=f"exception_analyze_{site_name}",
                    error=True)
            else:
                ti.push_to_cb(feed_id=site_conn.config.feed_id, results=self.format_report(reports))


if __name__ == '__main__':
    config = load_config_from_file()
    stix_taxii = StixTaxii(config)
    reports = stix_taxii.analyze()

    #activate generator to send results
    for report in reports:
        pass