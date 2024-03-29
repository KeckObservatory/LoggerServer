import yaml
import pdb
import argparse
from flask import Flask, request, jsonify
from datetime import datetime
from urllib.parse import urlparse
from bson.json_util import dumps
import eventlet
from eventlet import wsgi
from zmq_server import get_mongodb, get_schema_keys, process_query, get_default_config_loc, validate_log

app = Flask(__name__)
app.config.from_object(__name__)

@app.route('/heartbeat', methods=["GET"])
def heartbeat():
    return "OK", 200


@app.route('/api/log/new_log', methods=["PUT"])
def new_log():
    content = request.form
    loggername = content.get('loggername', 'DDOI')
    log = {
        'utc_sent': content.get('utc_sent', None),
        'utc_received': datetime.utcnow(),
        'hostname': str(urlparse(request.base_url).hostname),
        'level': content.get('level', None),
        'loggername': loggername,
        'message': content.get('message', None),
    }
    dbconfig = config[f'{loggername.upper()}_DATA_BASE']
    db_name = dbconfig.get('DB_NAME')
    db_client = get_mongodb(db_name)
    log_coll_name = dbconfig.get('LOG_COLL_NAME')
    log_schema = get_schema_keys(dbconfig.get('LOG_SCHEMA'))
    for key in log_schema:
        log[key] = content.get(key, None)


    # sanitize log
    valid_schema = [ *dbconfig.get('BASE_LOG_SCHEMA'), *dbconfig.get('LOG_SCHEMA')]
    resp = validate_log(log, valid_schema)
    if resp:
        return resp, 405
    id = db_client[log_coll_name].insert_one(log)
    return "Log submitted", 201


@app.route('/api/log/get_logs', methods=["GET"])
def get_logs():
    startDate = request.args.get('start_date', None, type=str)
    minutes = request.args.get('minutes', None, type=int)
    endDate = request.args.get('end_date', None, type=str)
    nLogs = request.args.get('n_logs', 1500, type=int)
    loggername = request.args.get('loggername', 'DDOI', type=str)
    dateFormat = request.args.get('date_format', '%Y-%m-%d', type=str)
    
    dbconfig = config[f'{loggername.upper()}_DATA_BASE']
    db_name = dbconfig.get('DB_NAME')
    log_coll_name = dbconfig.get('LOG_COLL_NAME')
    log_schema = get_schema_keys(dbconfig.get('LOG_SCHEMA'))

    query_params = { key: request.args.get(key, None) for key in log_schema }

    find, sort = process_query(startDate, endDate, nLogs, minutes, dateFormat, **query_params)
    
    db_client = get_mongodb(db_name)

    cursor = db_client[log_coll_name].find(find) 
    if len(sort) > 0:
        cursor = cursor.sort(sort) 

    cursor = cursor.limit(nLogs)
    logs = [x for x in cursor]
    if len(logs) > 0:
        res = dumps(logs)
        return res
    else:
        return jsonify([]), 200


if __name__ == "__main__":

    parser = argparse.ArgumentParser(description="Create zmq server")
    parser.add_argument('--configPath', type=str, required=False, default=get_default_config_loc(),
                         help="subsystem specific logs")
    args = parser.parse_args()
    with open(args.configPath, 'r') as f:
        config = yaml.safe_load(f)
    flaskconfig = config['FLASK_SERVER']
    url = flaskconfig.get('url')
    port = int(flaskconfig.get('port', None))
    wsgi.server(eventlet.listen((url, port)), app)
