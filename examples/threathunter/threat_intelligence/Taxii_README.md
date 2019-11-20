# TAXII Connector
Connector for pulling and converting STIX information from TAXII Service Providers into CB Feeds.

## Requirements/Installation

The file `requirements.txt` contains a list of dependencies for this project. After cloning this repository, run the following command from the `examples/threathunter/threat_intelligence` directory:

```
pip install -r ./requirements.txt
```

## Introduction
This document describes how to configure the CB ThreatHunter TAXII connector.
This connector allows for the importing of STIX data by querying one or more TAXII services, retrieving that data and then converting it into CB feeds using the CB JSON format for IOCs.

## Setup - TAXII Configuration File
The TAXII connector uses the configuration file `config.yml`. An example configuration file is available [here.](config.yml) An explanation of each entry in the configuration file is provided in the example.


## Running the Connector
The connector can be activated by running the python 3 file `stix_taxii.py`. The connector will attempt to connect to your TAXII service(s), poll the collection(s), retrieve the STIX data, and send it to the ThreatHunter Feed specified in your `config.yml` file.


## File Names and Functionalities
The connector code is located in the `examples/threathunter/threat_intelligence` directory. Its functionality is split into the following files:

1. [`stix_taxii.py`](stix_taxii.py):
Contains the logic to connect to TAXII servers via the `cabby` library.

2. [`config.yml`](config.yml):
Enables per-TAXII-server-level configuration options. See the [example configuration file](config.yml) for more details.


3. [`stix_parse.py`](stix_parse.py):
Contains the logic to parse STIX observables from the XML data returned by the TAXII server.
The following IOC types are extracted from STIX data:

* MD5 Hashes
* Domain Names
* IP-Addresses
* IP-Address Ranges

4. [`feed_helper.py`](feed_helper.py):
Contains the logic to advance the `begin_date` and `end_date` fields while polling the TAXII server to iteratively get per-collection STIX content.
This is tied to the `start_date` and `minutes_to_advance` configuration options in your `config.yml`.

5. [`threatintel.py`](threatintel.py):
Contains the logic for validating reports and sending validated reports to ThreatHunter. Also allows for conversion between result dictonaries into ThreatHunter `Report` objects.

6. [`get_feed_ids.py`](get_feed_ids.py):
Contains the logic to check ThreatHunter for available feeds to send results to.

7. [`results.py`](results.py):
Contains AnalysisResult and IOC classes and methods.