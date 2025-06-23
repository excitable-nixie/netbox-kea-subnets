#!/usr/bin/env python3

from sys import stdout
import pynetbox
import click
import netaddr
import json
import yaml
import jinja2
import dotenv
import zlib
import logging

dotenv.load_dotenv()

def filter_host_ip(value, hostnum=0):
    return netaddr.IPNetwork(value)[hostnum]

def filter_ip(value):
    return netaddr.IPNetwork(value).ip

@click.command
@click.option('--url', envvar='NETBOX_URL', show_default='NETBOX_URL', required=True, help='Netbox base URL')
@click.option('--token', envvar='NETBOX_TOKEN', show_default='NETBOX_TOKEN', required=True, help='Netbox API Token')
@click.option('--parent-prefix', envvar='PARENT_PREFIX', default='0.0.0.0/0', show_default=True, help='Parent prefix (IPv4 or IPv6)')
@click.option('--incpude-parent-prefix', envvar='INCLUDE_PARENT_PREFIX', default=True, show_default=True, help='If the parent prefix is in netbox it should be returned. if filtering for a single prefix, true, if filtering for multiple prefixes not nested in a parent prefix, true, if filtering for prefix under an exisitng parent, false.')
@click.option('--ip-range-role', envvar='RANGE_ROLE', default='dhcp-pool', show_default=True, help='Role slug for DHCP IP ranges')
@click.option('--config', envvar='OUTPUT_PATH', help='Kea config file')
@click.option('--template-path', envvar='TEMPLATE_PATH', default='./templates', show_default=True, help='Template search path. Must contain "subnet.yaml.j2".')
@click.option('--log-level', envvar='LOG_LEVEL', default='DEBUG', show_default=True, help='Controls infroamtion output of what the application is doing, and intermidate data.')

def main(url, token, parent_prefix, incpude_parent_prefix, ip_range_role, config, template_path, log_level):
    logging.basicConfig(
        level=log_level, 
        format='%(asctime)s - %(levelname)s - %(message)s'
    )
    _parent_prefix = netaddr.IPNetwork(parent_prefix)

    env = jinja2.Environment(
        loader=jinja2.FileSystemLoader(template_path),
        autoescape=jinja2.select_autoescape(),
    )
    env.filters['host_ip'] = filter_host_ip
    env.filters['ip'] = filter_ip

    nb = pynetbox.api(url, token)
    # If the parent prefix filter is itself a prefix in netbox it will result in a malfromed output
    if incpude_parent_prefix:
        prefixes = nb.ipam.prefixes.filter(status='active', within_include=parent_prefix)
    else:
        prefixes = nb.ipam.prefixes.filter(status='active', within=parent_prefix)
    logging.debug("retrieved ip prefixes: " + str(prefixes))
    ip_ranges = list(nb.ipam.ip_ranges.filter(status='active', role=ip_range_role))
    logging.debug("retrieved ip ranges: " + str(ip_ranges))
    ip_addresses = list(nb.ipam.ip_addresses.filter(status='dhcp', parent=parent_prefix))
    logging.debug("retrieved ip addresses: " + str(ip_addresses))
    subnets = []

    for prefix in prefixes:
        _prefix = netaddr.IPNetwork(prefix.prefix)

        logging.debug("processing prefix: " + str(_prefix))

        pools = []
        reservations = []

        for ip_range in filter(lambda r : netaddr.IPNetwork(r.start_address).ip in _prefix, ip_ranges):
            pools.append(ip_range)

        print(* pools)
        for ip_address in filter(lambda a : netaddr.IPNetwork(a.address).ip in _prefix, ip_addresses):
            reservations.append(ip_address)

        print(* reservations)

        if pools:
            subnet_template = env.get_template('subnet.yaml.j2')
            subnets.append(yaml.safe_load(subnet_template.render(
                # The Kea subnet ID is a 32 bit unsigned int.
                # We assume that CRC32 of the prefix is sufficiently unique.
                id=zlib.crc32(bytes(_prefix.ip)) % (1<<32),

                prefix=prefix,
                pools=pools,
                reservations=reservations
            )))
            
    if (config):
        config_json = yaml.safe_load(open(config, 'r'))
        
        if _parent_prefix.version == 4:
            config_json['Dhcp4']['subnet4'] = subnets
        elif _parent_prefix.version == 6:
            config_json['Dhcp6']['subnet6'] = subnets
        json.dump(config_json, stdout, indent=2)

    else:
        json.dump(subnets, stdout, indent=2)
    logging.debug("Raw config: ")
    logging.debug(* subnets)
if __name__ == '__main__':
    main()