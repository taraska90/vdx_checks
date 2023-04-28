from netmiko import ConnectHandler
import getpass
import subprocess
import re
import argparse
from textfsm import clitable


command_set_bgp_se = ['show ip bgp summary rbr all', 'show ipv6 bgp summary rbr all']
command_set_bgp_vrf = ['show vrf', 'show ip bgp summary vrf <vrf_name> rbridge-id all']
cmd_set_default = ['show interface status rbr all', 'show interface status rbrid all', 'show ip bgp routes 0.0.0.0/0', 'show ip route']


def get_auth_data(auth_flag='1pass'):
    user = ''
    password = ''
    if auth_flag == 'cli':
        user = input("Please enter username:\n")
        password = getpass.getpass(prompt='Enter switch password:\n')
    elif auth_flag == "1pass":
        one_password_output = subprocess.run(["op", "item", "get", "leaf_a", "--fields", "username,password"], stdout=subprocess.PIPE)
        user, password = (((one_password_output.stdout.decode()).rstrip()).split(','))
    authen_data = {'user': user, 'password': password}
    return authen_data


def get_output_from_device(host_params, cmd):
    net_connection = ConnectHandler(**host_params)
    result = net_connection.send_command(cmd)
    net_connection.disconnect()
    return result


def create_host_params(hostname, auth_data, device_type='brocade_vdx'):
    host_params = {
        'device_type': device_type,
        'host': hostname,
        'username': auth_data['user'],
        'password': auth_data['password']
    }
    return host_params

def check_leaf_type(host):
    result = re.search(r'(si|se)-(\w*)-.*', host)
    leaf_type = ''
    if (result.group(2) == 'siteA' or result.group(2) == 'siteB') and result.group(1) == 'si':
        leaf_type = 'vrf'
    elif result.group(1) == 'sii':
        leaf_type = 'si'
    elif result.group(1) == 'sei':
        leaf_type = 'se'
    return leaf_type

def get_structured_data(cli_command, connect_params, index_file='index', template_dir='ntc-template/templates'):
    output = get_output_from_device(connect_params, cli_command)
    cli_table = clitable.CliTable(index_file, template_dir)
    attributes = {'Command': cli_command, 'Vendor': connect_params['device_type']}
    cli_table.ParseCmd(output, attributes)
    header = list(cli_table.header)
    data_rows = [list(row) for row in cli_table]
    output_list = list()
    for rows in data_rows:
        output_dict = dict(zip(header, rows))
        output_list.append(output_dict)
    return output_list

def get_uplink_checks(state):
    '''Template: vdx_interface_status.template
    this template will gather information only from interfaces with description
    [{'Fo 1/0/51': {'inteface_index': True, 'connected': True, 'speed': True, 'is_uplink': True}},
    {'Fo 2/0/51': {'inteface_index': True, 'connected': False, 'speed': False, 'is_uplink': True}}]
    '''
    uplink_status = {}
    uplink_status_list = list()
    for uplink in state:
        uplink_status = {uplink['interface']: {}}
        if uplink['interface'] == 'Fo 1/0/51' or uplink['interface'] == 'Fo 2/0/51':
            uplink_status[uplink['interface']]['inteface_index'] = True
        else:
            uplink_status[uplink['interface']]['inteface_index'] = False
        if uplink['status'] == 'connected':
            uplink_status[uplink['interface']]['connected'] = True
        else:
            uplink_status[uplink['interface']]['connected'] = False
        if uplink['speed'] == '40G':
            uplink_status[uplink['interface']]['speed'] = True
        else:
            uplink_status[uplink['interface']]['speed'] = False
        if uplink['description'] == 'leaf l1 -> spine' or 'leaf l2 -> spine':
            uplink_status[uplink['interface']]['is_uplink'] = True
        else:
            uplink_status[uplink['interface']]['is_uplink'] = False
        uplink_status_list.append(uplink_status)
    return uplink_status_list

def check_uplinks(connect_p):
    uplink_state = get_structured_data(command_set_interfaces[0], connect_p)
    uplinks = get_uplink_checks(uplink_state)
    interface = str()
    for int_data in uplinks:
        for key in int_data.keys():
            interface = key
        if int_data[interface]['is_uplink']:
            print(f'UPLINK_CHECK Interface {interface}: PASSED')
            if int_data[interface]['inteface_index']:
                print(f'INDEX_CHECK Interface {interface}: PASSED')
            else:
                print(f'INDEX_CHECK Interface {interface}: FAILED')
            if int_data[interface]['connected']:
                print(f'CONNECTION_CHECK Interface {interface}: PASSED')
            else:
                print(f'CONNECTION_CHECK Interface {interface}: FAILED')
            if int_data[interface]['speed']:
                print(f'SPEED_CHECK Interface {interface}: PASSED')
            else:
                print(f'SPEED_CHECK Interface {interface}: FAILED')
        else:
            print(f'UPLINK_CHECK Interface {interface}: FAILED')


def get_uplink_speed(connect_p):
    ''' Template: vdx_speed_rate.template
    Two different lists for different uplinks
    [{'direction': 'Input', 'speed': '0.000280', 'rate': 'Mbits/sec'}, {'direction': 'Output', 'speed': '0.000280', 'rate': 'Mbits/sec'}]
    [{'direction': 'Input', 'speed': '0.000000', 'rate': 'Mbits/sec'}, {'direction': 'Output', 'speed': '0.000000', 'rate': 'Mbits/sec'}]

    Just manual checks for now, because I need to think how to realize speed check
    if it will be near with 0 value.
    '''
    speed_cli = ['show inter fo 1/0/51', 'show inter fo 2/0/51']
    speed_rate = list()
    for cmd in speed_cli:
        speed_rate = get_structured_data(cmd, connect_p)
        for s in speed_rate:
            direction = s['direction']
            speed = s['speed']
            rate = s['rate']
            print(f'SPEED_RATE_CHECK Command: {cmd} Direction: {direction} speed: {speed} rate: {rate}')
    return speed_rate

def get_isl_status(isl_state):
    '''
    Template: vdx_isl_status.template
    output:
    [{'port': 'Fo 1/0/49', 'status': 'connected', 'mode': 'ISL', 'speed': '40G', 'type': '40G-QSFP'},
    {'port': 'Fo 1/0/50', 'status': 'connected', 'mode': 'ISL', 'speed': '40G', 'type': '40G-QSFP'},
    {'port': 'Fo 2/0/49', 'status': 'connected', 'mode': 'ISL', 'speed': '40G', 'type': '40G-QSFP'},
    {'port': 'Fo 2/0/50', 'status': 'connected', 'mode': 'ISL', 'speed': '40G', 'type': '40G-QSFP'}]
    :return:
    '''
    isl_status_list = list()
    for isl in isl_state:
        isl_status = {isl['port']: {}}
        if isl['status'] == 'connected' and isl['mode'] == 'ISL' and isl['speed'] == '40G':
            isl_status[isl['port']]['isl_state'] = True
        else:
            isl_status[isl['port']]['isl_state'] = False
        isl_status_list.append(isl_status)
    return isl_status_list


def check_isl(connect_p):
    isl_status = get_structured_data(command_set_interfaces[1], connect_p)
    isl = get_isl_status(isl_status)
    if len(isl) == 4:
        print('ISL_CHECK Number of isl link PASSED')
    else:
        print('ISL_CHECK Number of isl link FAILED')
    for isl_data in isl:
        for key in isl_data.keys():
            interface = key
        if isl_data[interface]['isl_state']:
            print(f'ISL_CHECK Interface {interface} PASSED')
        else:
            print(f'ISL_CHECK Interface {interface} FAILED')


def get_bgp_summary(bgp_summary):
    '''
    Template: vdx_bgp_v4.template
    output:
    [{'rbr_id': '1', 'router_id': '1.1.1.1', 'neighbour': '1.1.1.1', 'remote_as': '71979', 'state': 'ESTAB'},
    {'rbr_id': '1', 'router_id': '1.1.1.1', 'neighbour': '1.1.1.1', 'remote_as': '71979', 'state': 'ESTAB'},
    {'rbr_id': '1', 'router_id': '1.1.1.1', 'neighbour': '1.1.1.1', 'remote_as': '71979', 'state': 'ADMDN'},
    {'rbr_id': '2', 'router_id': '1.1.1.1', 'neighbour': '1.1.1.1', 'remote_as': '71979', 'state': 'CONN'},
    {'rbr_id': '2', 'router_id': '1.1.1.1', 'neighbour': '1.1.1.1', 'remote_as': '71979', 'state': 'ESTAB'}]
    :return:
    '''
    bgp_status = {}
    bgp_status_list = list()
    for bgp in bgp_summary:
        bgp_status = {bgp['neighbour']: {}}
        if bgp['state'] == 'ESTAB':
            bgp_status[bgp['neighbour']]['state'] = True
        else:
            bgp_status[bgp['neighbour']]['state'] = False
        bgp_status_list.append(bgp_status)
    return bgp_status_list


def check_bgp_summary(connect_p):
    bgp_status = get_structured_data(command_set_bgp_si[0], connect_p)
    bgp_summary = get_bgp_summary(bgp_status)
    for bgp in bgp_summary:
        for key in bgp.keys():
            neighbor = key
        if bgp[neighbor]['state']:
            print(f'BGP_CHECK_NEIGHBOR: {neighbor} neighbor PASSED')
        else:
            print(f'BGP_CHECK router id: {neighbor} neighbor FAILED')

def check_default_route(connect_p):
    default_bgp = get_structured_data(cmd_set_default[2], connect_p)
    for bgp in default_bgp:
        if bgp['weight' == 0]:
            nh_cmd = cmd_set_default[3] + bgp['next_hop']
            show_ip_route = get_structured_data(nh_cmd, connect_p)
            if show_ip_route[0]['port'] == 'Ve 98':
                print(f'CHECK: {hostname} default route PASSED')
            else:
                print(f'CHECK: {hostname} default route FAILED')

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--host_name', type=str, required=True)
    args = parser.parse_args()
    hostname = args.host_name
    authentication = get_auth_data()
    #leaf_t = check_leaf_type()
    conn_param = create_host_params(hostname, authentication)
    check_uplinks(conn_param)
    get_uplink_speed(conn_param)
    check_isl(conn_param)
    check_bgp_summary(conn_param)
    check_default_route(conn_param)

if __name__ == "__main__":
    main()
