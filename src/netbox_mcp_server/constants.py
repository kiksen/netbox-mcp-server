INSTRUCTIONS = """
This mcp server is used for netbox. 

Some general netbox rules for vlan and prefix creation:
- A prefix can be called prefix, network or subnet
- each prefix needs to have a role: access or production
- production prefixes have vlans in the vlan range between 400 to 499
- this mcp server creates need to be part of a vlan_group to ensure there are no duplicate groups
- each prefix has the scope site. the scope site is derived from the site itself
- if the site you are creating a prefix has a tenant, set also the tenant of the site equal to the prefix
- always ask the user to verify all settings before creating a prefix with vlan id, site and role
- vlan names are derived from the desctipion and need to be not longer than 15 characters

To create a new prefix the user will ask to create a new network with the following subnet mask e.g. /24 for a specific site.
As a next step get the the correct site-summary.
If you know the site-summary get the next free prefix with the specific subnet size

IMPORTANT: When a tool returns multiple selectable items (e.g. site summaries, VLAN groups), always present them as interactive choices using the AskUserQuestion tool.
"""

# valid ipam roles
VALID_IPAM_ROLES = {"access", "production"}

# production vlan_range
PRODUCTION_VLAN_RANGE = (400, 499)


# Default object types for global search
DEFAULT_SEARCH_TYPES = [
    "dcim.device",  # Most common search target
    "dcim.site",  # Site names frequently searched
    "ipam.ipaddress",  # IP searches very common
    "dcim.interface",  # Interface names/descriptions
    "dcim.rack",  # Rack identifiers
    "ipam.vlan",  # VLAN names/IDs
    "circuits.circuit",  # Circuit identifiers
    "virtualization.virtualmachine",  # VM names
]
