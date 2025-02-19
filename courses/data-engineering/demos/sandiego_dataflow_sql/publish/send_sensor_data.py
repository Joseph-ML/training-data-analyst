#!/usr/bin/env python3

# Copyright 2021 Google Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import time
import gzip
import json
import logging
import argparse
import datetime
from google.cloud import pubsub

TIME_FORMAT = '%Y-%m-%d %H:%M:%S'
TOPIC = 'sandiego'
INPUT = 'sensor_obs2008.csv.gz'

def publish(publisher, topic, events):
   numobs = len(events)
   print(events[0])
   if numobs > 0:
       logging.info('Publishing {0} events from {1}'.format(numobs, json.loads(events[0])['timestamp']))
       for event_data in events:
         publisher.publish(topic,event_data.encode())

def get_timestamp(line):
   ## convert from bytes to str
   line = line.decode('utf-8')

   # look at first field of row
   timestamp = line.split(',')[0]
   return datetime.datetime.strptime(timestamp, TIME_FORMAT)

def convert_csv_to_json(line):
   # Convert incoming CSV row into expected format for Dataflow SQL
   line_arr = line.decode('utf-8').split(",")
   fields = "timestamp,latitude,longitude,freeway_id,freeway_dir,lane,speed".split(",")
   line_dict = dict(zip(fields,line_arr))
   line_dict['latitude'] = float(line_dict['latitude'])
   line_dict['longitude'] = float(line_dict['longitude'])
   line_dict['freeway_id'] = int(line_dict['freeway_id'])
   line_dict['lane'] = int(line_dict['lane'])
   line_dict['speed'] = float(line_dict['speed'])
   return json.dumps(line_dict)

def simulate(topic, ifp, firstObsTime, programStart, speedFactor):
   # sleep computation
   def compute_sleep_secs(obs_time):
      time_elapsed = (datetime.datetime.utcnow() - programStart).seconds
      sim_time_elapsed = (obs_time - firstObsTime).seconds / speedFactor
      return sim_time_elapsed - time_elapsed

   topublish = list()

   for line in ifp:
       event_data = line   # entire line of input CSV is the raw message
       obs_time = get_timestamp(line) # from first column

       # how much time should we sleep?
       if compute_sleep_secs(obs_time) > 1:
          # notify the accumulated topublish
          publish(publisher, topic, topublish) # notify accumulated messages
          topublish = list() # empty out list

          # recompute sleep, since notification takes a while
          to_sleep_secs = compute_sleep_secs(obs_time)
          if to_sleep_secs > 0:
             logging.info('Sleeping {} seconds'.format(to_sleep_secs))
             time.sleep(to_sleep_secs)
       event_data_json = convert_csv_to_json(event_data) #Put into Row JSON format.
       topublish.append(event_data_json)

   # left-over records; notify again
   publish(publisher, topic, topublish)

def peek_timestamp(ifp):
   # peek ahead to next line, get timestamp and go back
   pos = ifp.tell()
   line = ifp.readline()
   ifp.seek(pos)
   return get_timestamp(line)


if __name__ == '__main__':
   parser = argparse.ArgumentParser(description='Send sensor data to Cloud Pub/Sub in small groups, simulating real-time behavior')
   parser.add_argument('--speedFactor', help='Example: 60 implies 1 hour of data sent to Cloud Pub/Sub in 1 minute', required=True, type=float)
   parser.add_argument('--project', help='Example: --project $DEVSHELL_PROJECT_ID', required=True)
   args = parser.parse_args()

   # create Pub/Sub notification topic
   logging.basicConfig(format='%(levelname)s: %(message)s', level=logging.INFO)
   publisher = pubsub.PublisherClient()
   event_type = publisher.topic_path(args.project,TOPIC)
   try:
      publisher.get_topic(event_type)
      logging.info('Reusing pub/sub topic {}'.format(TOPIC))
   except:
      publisher.create_topic(event_type)
      logging.info('Creating pub/sub topic {}'.format(TOPIC))

   # notify about each line in the input file
   programStartTime = datetime.datetime.utcnow()
   with gzip.open(INPUT, 'rb') as ifp:
      header = ifp.readline()  # skip header
      firstObsTime = peek_timestamp(ifp)
      logging.info('Sending sensor data from {}'.format(firstObsTime))
      simulate(event_type, ifp, firstObsTime, programStartTime, args.speedFactor)
