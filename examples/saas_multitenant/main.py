"""SaaS Multi-Tenant example — Luso8 Cloud Platform integration.

Demonstrates:
- Tenant provisioning (generating Asterisk config fragments)
- ARI app namespacing for tenant isolation
- Per-tenant VoxtraApp instances
- SIP trunk provisioning

This is how Voxtra integrates with the Luso8 Admin Dashboard
for multi-tenant AI call center deployments.

Requirements:
    pip install voxtra[provisioning]
"""

import asyncio

from voxtra import VoxtraApp, SIPTrunk
from voxtra.provisioning import TenantProvisioner, TenantConfig


async def provision_new_tenant():
    """Example: Onboard a new tenant from the Luso8 Admin Dashboard."""

    provisioner = TenantProvisioner(output_dir="/etc/asterisk/voxtra.d")

    # Tenant config — typically received from the Luso8 Admin API
    tenant = TenantConfig(
        tenant_id="acme-corp",
        tenant_name="Acme Corporation",
        sip_trunk=SIPTrunk(
            host="sip.carrier.mw",
            port=5060,
            username="acme_trunk",
            password="trunk_secret_123",
            did="+265999123456",
            codecs=["ulaw", "alaw"],
        ),
        dids=["+265999123456", "+265888654321"],
        max_channels=20,
    )

    # Generate Asterisk config fragments
    files = provisioner.provision(tenant)

    # Write config files to /etc/asterisk/voxtra.d/
    provisioner.write_files(files)

    print(f"Provisioned tenant: {tenant.tenant_name}")
    print(f"  ARI app:  {tenant.ari_app_name}")
    print(f"  ARI user: {tenant.ari_username}")
    print(f"  Context:  {tenant.context}")
    print(f"  Files:    {list(files.keys())}")

    return tenant


async def run_tenant_app(tenant: TenantConfig):
    """Run a VoxtraApp for a specific tenant."""

    # Each tenant gets their own VoxtraApp with isolated ARI app name
    app = VoxtraApp(
        ari_url="http://pbx.luso8.cloud:8088",
        ari_user=tenant.ari_username,
        ari_password=tenant.ari_password,
        app_name=tenant.ari_app_name,  # Isolates Stasis events
    )

    @app.on_call
    async def handle(call):
        await call.answer()
        await call.play_file("hello-world")

        digit = await call.listen_dtmf(max_digits=1, timeout=15.0)
        if digit == "1":
            await call.transfer_to_queue("support")
        elif digit == "2":
            await call.transfer_to_queue("sales")
        else:
            await call.hangup()

    await app.run_async()


async def main():
    tenant = await provision_new_tenant()
    await run_tenant_app(tenant)


if __name__ == "__main__":
    asyncio.run(main())
