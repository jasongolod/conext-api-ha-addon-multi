from flask import Flask, jsonify
from flask_restful import Api, Resource
from pyModbusTCP.client import ModbusClient
from time import sleep
import json
import os
import logging

app = Flask(__name__)
api = Api(app)

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Hardcoded global configs
registers_data = {
    'battery': {
        'voltage': '70,2,1000',
        'temperature': '74,1,-273',
        'soc': '76,1,1',
        'soh': '88,1,1'
    },
    'inverter': {
        'state': '64,1,0',
        'enabled': '66,1,0',
        'faults': '68,1,0',
        'warnings': '69,1,0',
        'status': '122,1,0',
        'load': '120,1,0',
        'ac_in_volts': '126,1,10',
        'ac_in_freq': '130,1,10',
        'ac_out_volts': '142,1,10',
        'ac_out_freq': '146,1,10',
        'battery_volts': '154,1,10',
    },
    'cc': {
        'state': '64,1,0',
        'faults': '68,1,0',
        'warnings': '69,1,0',
        'status': '73,1,0',
        'pv_volts': '76,1,10',
        'pv_amps': '78,1,10',
        'battery_volts': '80,1,10',
        'output_power': '88,1,10',
        'daily_kwh': '90,1,10',
        'aux_status': '92,1,0',
        'association': '249,1,0'
    }
}

operating_state = {
    0: 'Invert',
    1: 'Grid Support',
    2: 'Sell',
    3: 'AC Passthru',
    4: 'Load Shave',
    5: 'Battery Support',
}

inverter_status = {
    0: 'AC Pass Through',
    1: 'Inverting',
    2: 'Grid Support',
}

cc_status = {
    0: 'Not Charging',
    1: 'Bulk',
    2: 'Absorption',
}

solar_association = {
    0: 'Not Associated',
    1: 'Solar 1',
    2: 'Solar 2',
}

# Load config.json
config_path = '/app/config.json'
gateways = {}
gateways_config = []
if os.path.exists(config_path):
    with open(config_path, 'r') as f:
        try:
            gateways_config = json.load(f)
            logger.info(f"Raw config content: {gateways_config}")
            logger.info(f"Config loaded as type: {type(gateways_config)}")
            if isinstance(gateways_config, dict):
                logger.info("Config is dict; converting to list")
                gateways_config = [gateways_config[k] for k in sorted(gateways_config.keys(), key=int) if k.isdigit() and isinstance(gateways_config[k], dict)]
            elif not isinstance(gateways_config, list):
                logger.error(f"Config is unexpected type {type(gateways_config)}; forcing to empty list")
                gateways_config = []
        except json.JSONDecodeError as e:
            logger.error(f"JSON decode error: {str(e)}")
            gateways_config = []
        except Exception as e:
            logger.error(f"Unexpected error loading config: {str(e)}")
            gateways_config = []
else:
    logger.warning("Config file not found; using empty list")
    gateways_config = []

# Build gateways dict
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
        logger.error(f"Missing key in gateway config at index {idx}: {str(e)} - skipping")
    except TypeError as e:
        logger.error(f"Type error in gateway config at index {idx}: {str(e)} - skipping")
if not gateways:
    logger.warning("No valid gateways configured")

def get_modbus_values(gateway, device, device_instance=None):
    logger.info(f"Querying {gateway}/{device}/{device_instance}")
    if gateway not in gateways:
        return {'error': f'Gateway {gateway} not found'}
    gw_config = gateways[gateway]
    host = gw_config['ip']
    port = gw_config['port']
    timeout = gw_config['timeout']
    devices = gw_config['device_ids'].get(device, {})
    register_data = registers_data.get(device, {})
    return_data = {}

    if not devices:
        return {'error': f'No {device} devices configured for gateway {gateway}'}

    for device_key in devices:
        if device_instance and device_instance != device_key:
            continue
        
        return_data[device_key] = {}
        for register_name in register_data:
            register_data_values = register_data[register_name].split(',')
            register = int(register_data_values[0])
            reg_len = int(register_data_values[1])
            extra = float(register_data_values[2])

            try:
                cxt = ModbusClient(host=host, port=port, auto_open=True, auto_close=True, debug=False, unit_id=devices[device_key], timeout=timeout)
                hold_reg_arr = cxt.read_holding_registers(register, reg_len)

                if hold_reg_arr is None:
                    raise ValueError("No data returned from register")
                
                if reg_len == 2:
                    if hold_reg_arr[0] == 65535:
                        converted_value = hold_reg_arr[1] - hold_reg_arr[0]
                    elif hold_reg_arr[0] > 0 and hold_reg_arr[0] < 50:
                        converted_value = hold_reg_arr[0] * 65536 + hold_reg_arr[1]
                    elif register in [130, 166]:
                        converted_value = hold_reg_arr[0]
                    else:
                        converted_value = hold_reg_arr[1]
                elif reg_len == 8:
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

                if device == "battery":
                    if register == 70:
                        converted_value /= extra
                    elif register == 74:
                        converted_value = converted_value * 0.01 + extra
                    elif register in [76, 88]:
                        converted_value = converted_value
                    else:
                        converted_value = converted_value

                if device == "inverter":
                    if register == 64:
                        converted_value = operating_state.get(converted_value, 'Unknown')
                    elif register == 122:
                        converted_value = inverter_status.get(converted_value, 'Unknown')
                    elif register in [120, 132, 154, 170, 172]:
                        converted_value = converted_value
                    elif register in [126, 130, 142, 144, 146, 148, 162, 166, 178, 180, 182, 184]:
                        converted_value /= extra
                    else:
                        converted_value = converted_value

                if device == "cc":
                    if register == 64:
                        converted_value = operating_state.get(converted_value, 'Unknown')
                    elif register == 73:
                        converted_value = cc_status.get(converted_value, 'Unknown')
                    elif register == 68:
                        converted_value = "Has Active Faults" if converted_value == 1 else "No Active Faults"
                    elif register == 69:
                        converted_value = "Has Active Warnings" if converted_value == 1 else "No Active Warnings"
                    elif register in [76, 78, 88, 90]:
                        converted_value /= extra
                    elif register in [80, 92]:
                        converted_value = converted_value
                    elif register == 249:
                        converted_value = solar_association.get(converted_value, 'Unknown')
                    else:
                        converted_value = converted_value

                return_data[device_key][register_name] = converted_value
            except Exception as e:
                logger.error(f"Error querying {gateway}/{device}/{device_key}/{register_name}: {str(e)}")
                return_data[device_key][register_name] = {"error": str(e)}
            sleep(0.1)
    
    return return_data

class Battery(Resource):
    def get(self, gateway, instance=None):
        data = get_modbus_values(gateway, "battery", instance)
        return data, 200 if data else ({"error": "No data returned"}, 404)

class Inverter(Resource):
    def get(self, gateway, instance=None):
        data = get_modbus_values(gateway, "inverter", instance)
        return data, 200 if data else ({"error": "No data returned"}, 404)

    def put(self, gateway, instance):
        return {"command": f"received for gateway: {gateway} instance: {instance}"}, 200

class CC(Resource):
    def get(self, gateway, instance=None):
        data = get_modbus_values(gateway, "cc", instance)
        return data, 200 if data else ({"error": "No data returned"}, 404)

    def put(self, gateway, instance):
        return {"command": f"received for gateway: {gateway} instance: {instance}"}, 200

class Index(Resource):
    def get(self):
        logger.info("Root endpoint accessed")
        return {"message": "Solar monitor API", "gateways": list(gateways.keys())}, 200

# Updated routes
api.add_resource(Battery, "/<string:gateway>/battery", "/<string:gateway>/battery/<string:instance>")
api.add_resource(Inverter, "/<string:gateway>/inverter", "/<string:gateway>/inverter/<string:instance>")
api.add_resource(CC, "/<string:gateway>/cc", "/<string:gateway>/cc/<string:instance>")
api.add_resource(Index, "/")

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=5000, debug=False)
