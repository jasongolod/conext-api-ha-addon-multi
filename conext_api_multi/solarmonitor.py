from flask import Flask, jsonify
from flask_restful import Api, Resource
from pyModbusTCP.client import ModbusClient
from time import sleep
import json
import os
import logging  # Added for error logging

app = Flask(__name__)
api = Api(app)

# Setup logging (outputs to console/HA logs)
logging.basicConfig(level=logging.ERROR)
logger = logging.getLogger(__name__)

# Hardcoded registers_data, etc. (unchanged from previous)

# Load config.json (unchanged)

# Build gateways dict (unchanged)

# Updated get_modbus_values with error handling
def get_modbus_values(gateway, device, device_instance=None):
    if gateway not in gateways:
        return {'error': 'Gateway not found'}  # Will lead to 404 in route
    
    gw_config = gateways[gateway]
    host = gw_config['ip']
    port = gw_config['port']
    timeout = gw_config['timeout']
    devices = gw_config['device_ids'].get(device, {})
    register_data = registers_data.get(device, {})
    return_data = {}

    for device_key in devices:
        if device_instance and device_instance != device_key:
            continue
        
        return_data[device_key] = {}
        for register_name in register_data:
            register_data_values = register_data[register_name].split(',')
            register = register_data_values[0]
            reg_len = register_data_values[1]
            extra = register_data_values[2]

            try:
                cxt = ModbusClient(host=host, port=port, auto_open=True, auto_close=True, debug=False, unit_id=devices[device_key], timeout=timeout)
                hold_reg_arr = cxt.read_holding_registers(int(register), int(reg_len))
                
                if hold_reg_arr is None:
                    raise ValueError("No data returned from register")
                
                # Parsing logic (unchanged)
                
                # ... (rest of parsing code unchanged)
                
                return_data[device_key][register_name] = converted_value if converted_value is not None else None
            except Exception as e:
                logger.error(f"Error querying {gateway}/{device}/{device_key}/{register_name}: {str(e)}")
                return_data[device_key][register_name] = {"error": str(e)}  # Return error message instead of crashing
            sleep(0.1)
    
    return return_data

# Updated Resources with status codes
class Battery(Resource):
    def get(self, gateway, instance=None):  # Indented under class
        data = get_modbus_values(gateway, "battery", instance)
        if 'error' in data:
            return jsonify(data), 404 if data['error'] == 'Gateway not found' else 502
        return data

class Inverter(Resource):
    def get(self, gateway, instance=None):
        data = get_modbus_values(gateway, "inverter", instance)
        if 'error' in data:
            return jsonify(data), 404 if data['error'] == 'Gateway not found' else 502
        return data

    def put(self, gateway, instance):
        return {"command": "received for gateway: {} instance: {}".format(gateway, instance)}

class CC(Resource):  # Line 83; no indentation
    def get(self, gateway, instance=None):  # Indented
        data = get_modbus_values(gateway, "cc", instance)
        if 'error' in data:
            return jsonify(data), 404 if data['error'] == 'Gateway not found' else 502
        return data

    def put(self, gateway, instance):
        return {"command": "received for gateway: {} instance: {}".format(gateway, instance)}

class Index(Resource):
    def get(self):
        return {"message": "Solar monitor API", "gateways": list(gateways.keys())}
# Routes unchanged

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=5000, debug=False)
