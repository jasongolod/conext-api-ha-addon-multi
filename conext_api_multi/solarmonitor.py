from flask import Flask, jsonify
from flask_restful import Api, Resource
from pyModbusTCP.client import ModbusClient
from time import sleep
import json
import os
import logging  # For error logging

app = Flask(__name__)
api = Api(app)

# Setup logging (outputs to console/HA logs)
logging.basicConfig(level=logging.ERROR)
logger = logging.getLogger(__name__)

# Hardcoded global configs (from typical Conext Modbus maps; update with official docs)
registers_data = {
    'battery': {
        'voltage': '70,2,1000',  # uint32 /1000 = V
        'temperature': '74,1,-273',  # *0.01 + extra (C)
        'soc': '76,1,1',  # %
        'soh': '88,1,1'   # %
        # Add more from maps, e.g., 'current': '72,2,1000'
    },
    'inverter': {
        'state': '64,1,0',  # Lookup operating_state
        'enabled': '66,1,0',  # 1=enabled
        'faults': '68,1,0',   # 1=has faults
        'warnings': '69,1,0', # 1=has warnings
        'status': '122,1,0',  # Lookup inverter_status
        'load': '120,1,0',    # W
        'ac_in_volts': '126,1,10',  # /10 = V
        'ac_in_freq': '130,1,10',   # /10 = Hz
        'ac_out_volts': '142,1,10',
        'ac_out_freq': '146,1,10',
        'battery_volts': '154,1,10',
        # Add more, e.g., 'name': '0,8,0' for string
    },
    'cc': {
        'state': '64,1,0',
        'faults': '68,1,0',
        'warnings': '69,1,0',
        'status': '73,1,0',  # Lookup cc_status
        'pv_volts': '76,1,10',
        'pv_amps': '78,1,10',
        'battery_volts': '80,1,10',
        'output_power': '88,1,10',  # /10 = W?
        'daily_kwh': '90,1,10',
        'aux_status': '92,1,0',
        'association': '249,1,0'  # Lookup solar_association
        # Add more
    }
}

operating_state = {
    0: 'Invert',
    1: 'Grid Support',
    2: 'Sell',
    3: 'AC Passthru',
    4: 'Load Shave',
    5: 'Battery Support',
    # Add full from maps, e.g., 8: 'Suspended', etc.
    # Defaults; update with proven values
}

inverter_status = {
    0: 'AC Pass Through',
    1: 'Inverting',
    2: 'Grid Support',
    # Add more from maps
}

cc_status = {
    0: 'Not Charging',
    1: 'Bulk',
    2: 'Absorption',
    # Add more
}

solar_association = {
    0: 'Not Associated',
    1: 'Solar 1',
    2: 'Solar 2',
    # Add more
}

# Load config.json with type check and conversion for HA list schemas
config_path = '/app/config.json'
gateways = {}
if os.path.exists(config_path):
    with open(config_path, 'r') as f:
        try:
            gateways_config = json.load(f)
            logger.info(f"Raw config content: {json.dumps(gateways_config)}")  # Log raw for debugging
            logger.info(f"Config loaded as type: {type(gateways_config)}")  # Log type
            if isinstance(gateways_config, dict):
                # Handle HA's indexed dict for lists (e.g., {'0': gw1, '1': gw2})
                logger.info("Config is dict; converting to list of values")
                gateways_config = [gateways_config[k] for k in sorted(gateways_config.keys(), key=int) if k.isdigit() and isinstance(gateways_config[k], dict)]
            elif not isinstance(gateways_config, list):
                logger.error("Config is not a list or dict; forcing to empty list")
                gateways_config = []
            # Filter to only dict items in list
            gateways_config = [gw for gw in gateways_config if isinstance(gw, dict)]
        except json.JSONDecodeError as e:
            logger.error(f"JSON decode error: {str(e)}")
            gateways_config = []
else:
    gateways_config = []  # Fallback

# Build gateways dict with skipping invalid
for idx, gw in enumerate(gateways_config):
    try:
        name = gw['name']
        device_ids = {
            'battery': {d['name']: d['unit_id'] for d in gw.get('batteries', []) if isinstance(d, dict)},
            'inverter': {d['name']: d['unit_id'] for d in gw.get('inverters', []) if isinstance(d, dict)},
            'cc': {d['name']: d['unit_id'] for d in gw.get('charge_controllers', []) if isinstance(d, dict)},
        }
        gateways[name] = {
            'ip': gw['ip'],
            'port': gw.get('port', 503),
            'timeout': gw.get('timeout', 5),
            'device_ids': device_ids
        }
    except KeyError as e:
        logger.error(f"Missing key in gateway config at index {idx}: {str(e)} - skipping this gateway")
    except TypeError as e:
        logger.error(f"Type error in gateway config at index {idx} (likely non-dict gw): {str(e)} - skipping")
if not gateways:
    logger.warning("No valid gateways configured")

# Updated get_modbus_values with error handling
def get_modbus_values(gateway, device, device_instance=None):
    if gateway not in gateways:
        return {'error': 'Gateway not found'}
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
                
                if int(reg_len) == 2:
                    if hold_reg_arr[0] == 65535:
                        converted_value = hold_reg_arr[1] - hold_reg_arr[0]
                    elif hold_reg_arr[0] > 0 and hold_reg_arr[0] < 50:
                        converted_value = hold_reg_arr[0] * 65536 + hold_reg_arr[1]
                    elif register in ["130","166"]:
                        converted_value = hold_reg_arr[0]
                    else:
                        converted_value = hold_reg_arr[1]
                elif int(reg_len) == 8:
                    string_chars = ""
                    for a in hold_reg_arr:
                        if a > 0:
                            hex_string = hex(a)[2:]
                            if hex_string.endswith("00"):
                                hex_string = hex_string[:len(hex_string) - 2]
                            bytes_object = bytes.fromhex(hex_string)
                            string_chars += bytes_object.decode("ASCII")
                    converted_value = string_chars
                else:
                    converted_value = hold_reg_arr[0]

                # Scaling/parsing unchanged
                if device == "battery":
                    if register == "70":
                        converted_value /= int(extra)
                    elif register == "74":
                        converted_value = converted_value * 0.01 + int(extra)
                    elif register in ["76","88"]:
                        converted_value = converted_value
                    else:
                        converted_value = converted_value

                if device == "inverter":
                    if register == "64":
                        converted_value = operating_state.get(converted_value, 'Unknown')
                    elif register == "122":
                        converted_value = inverter_status.get(converted_value, 'Unknown')
                    elif register in ["120","132","154","170","172"]:
                        converted_value = converted_value
                    elif register in ["126","130","142","144","146","148","162","166","178","180","182","184"]:
                        converted_value /= int(extra)
                    else:
                        converted_value = converted_value

                if device == "cc":
                    if register == "64":
                        converted_value = operating_state.get(converted_value, 'Unknown')
                    elif register == "73":
                        converted_value = cc_status.get(converted_value, 'Unknown')
                    elif register == "68":
                        converted_value = "Has Active Faults" if converted_value == 1 else "No Active Faults"
                    elif register == "69":
                        converted_value = "Has Active Warnings" if converted_value == 1 else "No Active Warnings"
                    elif register in ["76","78","88","90"]:
                        converted_value /= int(extra)
                    elif register in ["80","92"]:
                        converted_value = converted_value
                    elif register == "249":
                        converted_value = solar_association.get(converted_value, 'Unknown')
                    else:
                        converted_value = converted_value

                return_data[device_key][register_name] = converted_value if converted_value is not None else None
            except Exception as e:
                logger.error(f"Error querying {gateway}/{device}/{device_key}/{register_name}: {str(e)}")
                return_data[device_key][register_name] = {"error": str(e)}  # Return error message instead of crashing
            sleep(0.1)
    
    return return_data

# Updated Resources with status codes
class Battery(Resource):
    def get(self, gateway, instance=None):
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

class CC(Resource):
    def get(self, gateway, instance=None):
        data = get_modbus_values(gateway, "cc", instance)
        if 'error' in data:
            return jsonify(data), 404 if data['error'] == 'Gateway not found' else 502
        return data

    def put(self, gateway, instance):
        return {"command": "received for gateway: {} instance: {}".format(gateway, instance)}

class Index(Resource):
    def get(self):
        return {"message": "Solar monitor API", "gateways": list(gateways.keys())}

# Updated routes with <gateway>
api.add_resource(Battery, "/<string:gateway>/battery", "/<string:gateway>/battery/<string:instance>")
api.add_resource(Inverter, "/<string:gateway>/inverter", "/<string:gateway>/inverter/<string:instance>")
api.add_resource(CC, "/<string:gateway>/cc", "/<string:gateway>/cc/<string:instance>")
api.add_resource(Index, "/")

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=5000, debug=False)
