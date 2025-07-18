from flask import Flask, jsonify
from flask_restful import Api, Resource
from pyModbusTCP.client import ModbusClient
import paho.mqtt.client as mqtt
from time import sleep
import json
import os
import logging
import threading

app = Flask(__name__)
api = Api(app)

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# MQTT configuration
MQTT_BROKER = os.getenv('MQTT_BROKER', 'core-mosquitto')
MQTT_PORT = int(os.getenv('MQTT_PORT', 1883))
MQTT_USERNAME = os.getenv('MQTT_USERNAME', '')
MQTT_PASSWORD = os.getenv('MQTT_PASSWORD', '')
MQTT_DISCOVERY_PREFIX = 'homeassistant'

# MQTT client with MQTTv5
mqtt_client = mqtt.Client(protocol=mqtt.MQTTv5)
if MQTT_USERNAME and MQTT_PASSWORD:
    mqtt_client.username_pw_set(MQTT_USERNAME, MQTT_PASSWORD)

def on_connect(client, userdata, flags, rc, properties=None):
    if rc == 0:
        logger.info("Connected to MQTT broker")
    else:
        logger.error(f"Failed to connect to MQTT broker, return code {rc}")

mqtt_client.on_connect = on_connect

# Reconnect logic
def connect_mqtt():
    try:
        mqtt_client.connect(MQTT_BROKER, MQTT_PORT)
        mqtt_client.loop_start()
    except Exception as e:
        logger.error(f"Failed to connect to MQTT broker: {str(e)}")
        sleep(5)
        connect_mqtt()

threading.Thread(target=connect_mqtt, daemon=True).start()

# Hardcoded global configs
registers_data = {
    'battery': {
        'voltage': '70,2,1000',  # uint32 /1000 = V
        'temperature': '74,1,-273',  # *0.01 + extra (C)
        'soc': '76,1,1',  # %
        'soh': '88,1,1'   # %
    },
    'powermeter': {
        'power': '1251,2,0.1',  # int32, scale 0.1, W
        'voltage': '1271,1,0.1',  # uint16, scale 0.1, V
        'current': '1281,2,0.1',  # int32, scale 0.1, A
        'energy': '1301,4,0.001'  # int64, scale 0.001, kWh
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
    },
    'ags': {
        'state': '64,1,0',
        'faults': '68,1,0',
        'warnings': '69,1,0',
        'gen_state': '70,1,0',
        'start_mode': '72,1,0'
    },
    'scp': {
        'state': '64,1,0',
        'faults': '68,1,0',
        'warnings': '69,1,0',
        'display_status': '70,1,0'
    },
    'gridtie': {
        'state': '64,1,0',
        'faults': '68,1,0',
        'warnings': '69,1,0',
        'pv_volts': '76,1,10',
        'pv_power': '88,1,10'
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

ags_state = {
    0: 'Stopped',
    1: 'Running',
    2: 'Fault'
}

scp_status = {
    0: 'Idle',
    1: 'Active'
}

gridtie_status = {
    0: 'Idle',
    1: 'Producing'
}

# Global gateways dict
gateways = {}

# Track failed devices to avoid repeated queries
failed_devices = {}

# Load config.json
config_path = '/app/config.json'
gateways_config = []
if os.path.exists(config_path):
    with open(config_path, 'r') as f:
        try:
            raw_config = json.load(f)
            logger.info(f"Raw config content: {raw_config}")
            logger.info(f"Config loaded as type: {type(raw_config)}")
            if isinstance(raw_config, str):
                try:
                    gateways_config = json.loads(raw_config)
                except json.JSONDecodeError as e:
                    logger.error(f"JSON decode error in string config: {str(e)}")
                    gateways_config = []
            elif isinstance(raw_config, dict):
                logger.info("Config is dict; converting to list")
                gateways_config = [raw_config[k] for k in sorted(raw_config.keys(), key=int) if k.isdigit() and isinstance(raw_config[k], dict)]
            elif isinstance(raw_config, list):
                gateways_config = raw_config
            else:
                logger.error(f"Config is unexpected type {type(raw_config)}; forcing to empty list")
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

# Build gateways dict and publish MQTT discovery
for idx, gw in enumerate(gateways_config):
    try:
        name = gw['name']
        device_ids = {
            'battery': {d['name']: d['unit_id'] for d in gw.get('batteries', []) if isinstance(d, dict)},
            'powermeter': {d['name']: d['unit_id'] for d in gw.get('powermeter', []) if isinstance(d, dict)},
            'inverter': {d['name']: d['unit_id'] for d in gw.get('inverters', []) if isinstance(d, dict)},
            'cc': {d['name']: d['unit_id'] for d in gw.get('charge_controllers', []) if isinstance(d, dict)},
            'ags': {d['name']: d['unit_id'] for d in gw.get('ags', []) if isinstance(d, dict)},
            'scp': {d['name']: d['unit_id'] for d in gw.get('scp', []) if isinstance(d, dict)},
            'gridtie': {d['name']: d['unit_id'] for d in gw.get('gridtie', []) if isinstance(d, dict)}
        }
        gateways[name] = {
            'ip': gw['ip'],
            'port': gw.get('port', 503),
            'timeout': gw.get('timeout', 5),
            'device_ids': device_ids
        }
        
        # Publish MQTT discovery for each device
        for device_type, devices in device_ids.items():
            for device_name, unit_id in devices.items():
                device_id = f"{name}_{device_name}"
                device_config = {
                    "name": device_name,
                    "identifiers": [device_id],
                    "manufacturer": "Schneider Electric",
                    "model": device_type.capitalize(),
                    "via_device": name
                }
                for register_name in registers_data[device_type]:
                    entity_id = f"sensor.{device_id}_{register_name}"
                    topic = f"{MQTT_DISCOVERY_PREFIX}/sensor/{device_id}/{register_name}/config"
                    unit = ""
                    if device_type == "battery":
                        if register_name == "voltage" or register_name == "battery_volts":
                            unit = "V"
                        elif register_name == "temperature":
                            unit = "°C"
                        elif register_name in ["soc", "soh"]:
                            unit = "%"
                    elif device_type == "powermeter":
                        if register_name == "power":
                            unit = "W"
                        elif register_name == "voltage":
                            unit = "V"
                        elif register_name == "current":
                            unit = "A"
                        elif register_name == "energy":
                            unit = "kWh"
                    elif device_type == "inverter":
                        if register_name in ["ac_in_volts", "ac_out_volts", "battery_volts"]:
                            unit = "V"
                        elif register_name in ["ac_in_freq", "ac_out_freq"]:
                            unit = "Hz"
                        elif register_name == "load":
                            unit = "W"
                    elif device_type == "cc":
                        if register_name in ["pv_volts", "battery_volts"]:
                            unit = "V"
                        elif register_name == "pv_amps":
                            unit = "A"
                        elif register_name in ["output_power", "daily_kwh"]:
                            unit = "W" if register_name == "output_power" else "kWh"
                    config = {
                        "name": f"{device_name} {register_name.replace('_', ' ').title()}",
                        "state_topic": f"conext/{name}/{device_type}/{device_name}/{register_name}",
                        "unique_id": entity_id,
                        "device": device_config,
                        "unit_of_measurement": unit,
                        "value_template": "{{ value_json.value }}"
                    }
                    mqtt_client.publish(topic, json.dumps(config), retain=True)
    except KeyError as e:
        logger.error(f"Missing key in gateway config at index {idx}: {str(e)}")
        return {"error": f"Missing key in gateway config: {str(e)}"}, 500
    except TypeError as e:
        logger.error(f"Type error in gateway config at index {idx}: {str(e)}")
        return {"error": f"Type error in gateway config: {str(e)}"}, 500
if not gateways:
    logger.warning("No valid gateways configured")
    return {"error": "No valid gateways configured"}, 500
else:
    logger.info(f"Loaded gateways: {list(gateways.keys())}")

def get_modbus_values(gateway, device, device_instance=None):
    logger.info(f"Querying {gateway}/{device}/{device_instance}")
    if gateway not in gateways:
        return {'error': f'Gateway {gateway} not found'}, 404
    gw_config = gateways[gateway]
    host = gw_config['ip']
    port = gw_config['port']
    timeout = gw_config['timeout']
    devices = gw_config['device_ids'].get(device, {})
    register_data = registers_data.get(device, {})
    return_data = {}

    if not devices:
        return {'error': f'No {device} devices configured for gateway {gateway}'}, 404

    for device_key in devices:
        if device_instance and device_instance != device_key:
            continue
        
        # Skip if device has failed repeatedly
        device_id = f"{gateway}_{device}_{device_key}"
        if device_id in failed_devices and failed_devices[device_id] >= 5:
            logger.debug(f"Skipping {device_id} due to repeated failures")
            return_data[device_key] = {"error": f"Device {device_key} skipped due to repeated failures"}
            continue

        return_data[device_key] = {}
        for register_name in register_data:
            register_data_values = register_data[register_name].split(',')
            register = int(register_data_values[0])
            reg_len = int(register_data_values[1])
            extra = float(register_data_values[2])

            try:
                cxt = ModbusClient(host=host, port=port, auto_open=True, auto_close=True, unit_id=devices[device_key], timeout=timeout)
                if not cxt.is_open:
                    raise ValueError(f"Failed to connect to {host}:{port} with unit_id {devices[device_key]}")
                hold_reg_arr = cxt.read_holding_registers(register, reg_len)

                if hold_reg_arr is None:
                    raise ValueError(f"No data returned from register {register} for {device_key}")
                
                # Reset failure count on success
                if device_id in failed_devices:
                    del failed_devices[device_id]

                if reg_len == 2:
                    if hold_reg_arr[0] == 65535:
                        converted_value = hold_reg_arr[1] - hold_reg_arr[0]
                    elif hold_reg_arr[0] > 0 and hold_reg_arr[0] < 50:
                        converted_value = hold_reg_arr[0] * 65536 + hold_reg_arr[1]
                    elif register in [130, 166]:
                        converted_value = hold_reg_arr[0]
                    else:
                        converted_value = hold_reg_arr[1]
                elif reg_len == 4:
                    converted_value = (hold_reg_arr[0] << 48) + (hold_reg_arr[1] << 32) + (hold_reg_arr[2] << 16) + hold_reg_arr[3]
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

                if device == "powermeter":
                    converted_value *= extra  # Scale for power, voltage, current, energy

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

                if device == "ags":
                    if register == 64:
                        converted_value = operating_state.get(converted_value, 'Unknown')
                    elif register == 70:
                        converted_value = ags_state.get(converted_value, 'Unknown')
                    elif register in [68, 69, 72]:
                        converted_value = converted_value
                    else:
                        converted_value = converted_value

                if device == "scp":
                    if register == 64:
                        converted_value = operating_state.get(converted_value, 'Unknown')
                    elif register == 70:
                        converted_value = scp_status.get(converted_value, 'Unknown')
                    elif register in [68, 69]:
                        converted_value = converted_value
                    else:
                        converted_value = converted_value

                if device == "gridtie":
                    if register == 64:
                        converted_value = operating_state.get(converted_value, 'Unknown')
                    elif register in [76, 88]:
                        converted_value /= extra
                    elif register in [68, 69]:
                        converted_value = converted_value
                    else:
                        converted_value = converted_value

                return_data[device_key][register_name] = converted_value
                # Publish to MQTT
                mqtt_topic = f"conext/{gateway}/{device}/{device_key}/{register_name}"
                mqtt_payload = {"value": converted_value}
                mqtt_client.publish(mqtt_topic, json.dumps(mqtt_payload))
            except Exception as e:
                logger.error(f"Error querying {gateway}/{device}/{device_key}/{register_name}: {str(e)}")
                return_data[device_key][register_name] = {"error": str(e)}
                # Track failures
                failed_devices[device_id] = failed_devices.get(device_id, 0) + 1
                # Publish error to MQTT
                mqtt_topic = f"conext/{gateway}/{device}/{device_key}/{register_name}"
                mqtt_payload = {"value": str(e)}
                mqtt_client.publish(mqtt_topic, json.dumps(mqtt_payload))
            sleep(0.1)
    
    return return_data, 200 if return_data else ({'error': 'No data returned'}, 404)

class Battery(Resource):
    def get(self, gateway, instance=None):
        result = get_modbus_values(gateway, "battery", instance)
        return result if isinstance(result, tuple) else (result, 500)

class PowerMeter(Resource):
    def get(self, gateway, instance=None):
        result = get_modbus_values(gateway, "powermeter", instance)
        return result if isinstance(result, tuple) else (result, 500)

class Inverter(Resource):
    def get(self, gateway, instance=None):
        result = get_modbus_values(gateway, "inverter", instance)
        return result if isinstance(result, tuple) else (result, 500)

    def put(self, gateway, instance):
        return {"command": f"received for gateway: {gateway} instance: {instance}"}, 200

class CC(Resource):
    def get(self, gateway, instance=None):
        result = get_modbus_values(gateway, "cc", instance)
        return result if isinstance(result, tuple) else (result, 500)

    def put(self, gateway, instance):
        return {"command": f"received for gateway: {gateway} instance: {instance}"}, 200

class AGS(Resource):
    def get(self, gateway, instance=None):
        result = get_modbus_values(gateway, "ags", instance)
        return result if isinstance(result, tuple) else (result, 500)

    def put(self, gateway, instance):
        return {"command": f"received for gateway: {gateway} instance: {instance}"}, 200

class SCP(Resource):
    def get(self, gateway, instance=None):
        result = get_modbus_values(gateway, "scp", instance)
        return result if isinstance(result, tuple) else (result, 500)

    def put(self, gateway, instance):
        return {"command": f"received for gateway: {gateway} instance: {instance}"}, 200

class GridTie(Resource):
    def get(self, gateway, instance=None):
        result = get_modbus_values(gateway, "gridtie", instance)
        return result if isinstance(result, tuple) else (result, 500)

    def put(self, gateway, instance):
        return {"command": f"received for gateway: {gateway} instance: {instance}"}, 200

class Index(Resource):
    def get(self):
        logger.info(f"Root endpoint accessed, gateways: {list(gateways.keys())}")
        return {"message": "Solar monitor API", "gateways": list(gateways.keys())}, 200

# Updated routes
api.add_resource(Battery, "/<string:gateway>/battery", "/<string:gateway>/battery/<string:instance>")
api.add_resource(PowerMeter, "/<string:gateway>/powermeter", "/<string:gateway>/powermeter/<string:instance>")
api.add_resource(Inverter, "/<string:gateway>/inverter", "/<string:gateway>/inverter/<string:instance>")
api.add_resource(CC, "/<string:gateway>/cc", "/<string:gateway>/cc/<string:instance>")
api.add_resource(AGS, "/<string:gateway>/ags", "/<string:gateway>/ags/<string:instance>")
api.add_resource(SCP, "/<string:gateway>/scp", "/<string:gateway>/scp/<string:instance>")
api.add_resource(GridTie, "/<string:gateway>/gridtie", "/<string:gateway>/gridtie/<string:instance>")
api.add_resource(Index, "/")

# Background thread to periodically update MQTT
def update_mqtt():
    while True:
        has_devices = False
        for gateway in gateways:
            for device_type in gateways[gateway]['device_ids']:
                for device_name in gateways[gateway]['device_ids'][device_type]:
                    device_id = f"{gateway}_{device_type}_{device_name}"
                    if device_id in failed_devices and failed_devices[device_id] >= 5:
                        logger.debug(f"Skipping {device_id} due to repeated failures")
                        continue
                    get_modbus_values(gateway, device_type, device_name)
                    has_devices = True
        if not has_devices:
            logger.info("No devices configured or all failed; skipping MQTT update")
            sleep(60)  # Wait longer if no devices
            continue
        sleep(10)  # Update every 10 seconds

threading.Thread(target=update_mqtt, daemon=True).start()

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=5000, debug=False)
