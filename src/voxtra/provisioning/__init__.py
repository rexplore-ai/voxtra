"""Tenant provisioning for multi-tenant Voxtra deployments.

Provides:
- TenantProvisioner: Generates Asterisk config fragments and ARI users
- Config templates: Jinja2 templates for pjsip.conf, extensions.conf
- SSH deployment helper: Push config to Asterisk servers
"""

from voxtra.provisioning.provisioner import TenantProvisioner, TenantConfig

__all__ = [
    "TenantProvisioner",
    "TenantConfig",
]
