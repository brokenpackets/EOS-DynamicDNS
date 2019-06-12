import jsonrpclib
import json
import re


'''
Script to automate changing tunnel destination and local-id on vEOS Router platform.

Example Tunnel Config:
    interface Tunnel0
        !! Dyn_dest = remote.example.com
        mtu 1400
        ip address 1.0.3.1/24
        tunnel mode gre
        tunnel source interface Ethernet1
        tunnel ipsec profile vrouter
        tunnel destination 192.0.2.2

Example Local-ID Config:
    ip security
       ike policy ike-vrouter
          !! Dyn_src = local.example.com
          local-id 192.0.2.1

If remote.example.com suddenly resolves to 192.0.2.254, the next time the
script runs, it will update the tunnel destination field to match.

Requirements:
* DNS client configured on vEOS,
* Comment created in tunnel config with "Dyn_dest = " as a prefix to the fqdn.
    Create with 'comment' cli syntax.
* Management API Unix-socket configured.
    management api http-commands
        no shutdown
        unix-socket
* Primary job created to watch tunnel interface status:
    event-handler Tunnel0
      trigger on-intf Tunnel 0
      delay 0
      action bash python /mnt/flash/vRouter_dyndns.py
* Cron job created to run script periodically in case of delay between DNS and
    intf status.
* Script regex only supports IPv4 currently. Can add v6 support if needed.

Example Cron:
* * * * */5 python /mnt/flash/vRouter_dyndns.py

'''

#limits scope of for-loop to interfaces
regex = re.compile('interface .*')
#Looks for Dyn_dest = 'fqdn'
regex2 = re.compile('Dyn_dest = (.*)')
#match against tunnel destination
Dyn_tun_dest = re.compile('tunnel destination (.*)')
#used to find the resolved IP address in a ping.
capture_resolution = re.compile('PING .*?\(([0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3})\)')
#match ike policies used for tunnel.
ikeProfile = re.compile('ike policy (.*)')
#identify if local-id is specified.
localID = re.compile('Dyn_src = (.*)')
#eval localID
Dyn_tun_src = re.compile('local-id (.*)')

def main():
    #SESSION SETUP FOR eAPI TO DEVICE, uses unix socket
    url = "unix:/var/run/command-api.sock"
    ss = jsonrpclib.Server(url)

    #CONNECT TO DEVICE
    # Grab running-config, strip list, and parse out 'cmds' dict.
    response = ss.runCmds( 1, [ 'show running-config' ] )[0]['cmds']
    # generate list of keys from running-config (top level configs).
    # match keys against regex, and add to list.
    newlist = [x for x in response.keys() if regex.match(x)]
    # loop through list of matching keys.
    for item in newlist:
        # Loop over item comments
        for value in response[item]['comments']:
            # match comment against regex2
            if regex2.match(value):
                # set fqdn variable as (.*) field of regex2, should match fqdn only.
                fqdn = regex2.match(value).group(1)
                # Ping from device using fqdn, break response out of list, and parse 'messages' dict.
                dns_lookup = ss.runCmds(1, ['ping '+fqdn+' repeat 1'] )[0]['messages']
                # set resolved_ip var as ([0-9]{1,3}\... etc) regex to parse IP from ping response.
                resolved_ip = capture_resolution.match(dns_lookup[0]).group(1)
                # Parse configuration line for tunnel destination
                config_line = [x for x in response[item]['cmds'] if Dyn_tun_dest.match(x)][0]
                # Grab currently installed tunnel destination IP and store as var.
                current_ip = Dyn_tun_dest.match(config_line).group(1)
                # Check currently installed dest IP vs DNS response IP
                if current_ip != resolved_ip:
                    # If IPs don't match, push DNS response IP to tunnel dest field.
                    finaloutput = ss.runCmds( 1, [ 'configure', item,
                    '   tunnel destination '+resolved_ip ] )
    ipsec = response['ip security']['cmds']
    ipseclist = [x for x in ipsec.keys() if ikeProfile.match(x)]
    for item in ipseclist:
        for value in ipsec[item]['comments']:
            if localID.match(value):
                selfFQDN = localID.match(value).group(1)
                selfdns_lookup = ss.runCmds(1, ['ping '+selfFQDN+' repeat 1'] )[0]['messages']
                selfresolved_ip = capture_resolution.match(selfdns_lookup[0]).group(1)
                config_line = [x for x in ipsec[item]['cmds'] if Dyn_tun_src.match(x)][0]
                # Grab currently installed tunnel destination IP and store as var.
                selfcurrent_ip = Dyn_tun_src.match(config_line).group(1)
                # Check currently installed dest IP vs DNS response IP
                if selfcurrent_ip != selfresolved_ip:
                    # If IPs don't match, push DNS response IP to tunnel dest field.
                    finaloutput = ss.runCmds( 1, [ 'configure', 'ip security', item,
                    '   local-id '+selfresolved_ip ] )
if __name__ == "__main__":
    main()
