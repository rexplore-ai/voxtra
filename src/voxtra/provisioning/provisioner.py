"""TenantProvisioner — generates Asterisk config for multi-tenant SaaS.

Each tenant gets:
- A unique ARI app name (e.g. "voxtra-tenant-acme")
- A unique ARI user with credentials
- PJSIP endpoint/auth/aor for their SIP trunk
- Dialplan context routing calls to their Stasis app
- AudioSocket integration in dialplan

The provisioner generates config fragments that are included in the
main Asterisk config via #include directives. This is the "Config
Fragment Pattern" from the Voxtra architecture docs.
"""

from __future__ import annotations

import logging
import secrets
import string
from pathlib import Path
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, Field

from voxtra.types import SIPTrunk

if TYPE_CHECKING:
    from voxtra.ari.client import ARIClient

logger = logging.getLogger("voxtra.provisioning")


class TenantConfig(BaseModel):
    """Configuration for a single tenant.

    This is the input to the provisioner — typically received from
    the Luso8 Admin Dashboard API when a new tenant is onboarded.
    """

    tenant_id: str
    tenant_name: str = ""
    ari_app_name: str = ""        # auto-generated if empty
    ari_username: str = ""        # auto-generated if empty
    ari_password: str = ""        # auto-generated if empty
    sip_trunk: SIPTrunk | None = None
    dids: list[str] = Field(default_factory=list)  # DIDs assigned to tenant
    context: str = ""             # dialplan context, auto-generated if empty
    max_channels: int = 10        # max concurrent calls
    audiosocket_host: str = "127.0.0.1"
    audiosocket_port: int = 0     # 0 = auto-assign

    def model_post_init(self, __context: Any) -> None:
        slug = self.tenant_id.lower().replace(" ", "-")
        if not self.ari_app_name:
            self.ari_app_name = f"voxtra-{slug}"
        if not self.ari_username:
            self.ari_username = f"voxtra-{slug}"
        if not self.ari_password:
            self.ari_password = _generate_password(32)
        if not self.context:
            self.context = f"voxtra-{slug}-inbound"
        if not self.tenant_name:
            self.tenant_name = self.tenant_id


class TenantProvisioner:
    """Generates Asterisk configuration fragments for tenants.

    Usage::

        provisioner = TenantProvisioner(output_dir="/etc/asterisk/voxtra.d")

        config = TenantConfig(
            tenant_id="acme-corp",
            sip_trunk=SIPTrunk(host="sip.carrier.com", username="acme", password="s3cret"),
            dids=["+265999123456"],
        )

        files = provisioner.provision(config)
        # files = {
        #   "pjsip_acme-corp.conf": "...",
        #   "extensions_acme-corp.conf": "...",
        #   "ari_acme-corp.conf": "...",
        # }

        # Write to disk
        provisioner.write_files(files)

        # Reload Asterisk so the new configs take effect (requires a
        # connected ARIClient — typically the one your VoxtraApp owns).
        await provisioner.reload_asterisk(app.ari)
    """

    def __init__(
        self,
        output_dir: str | Path = "/etc/asterisk/voxtra.d",
    ) -> None:
        self.output_dir = Path(output_dir)

    def provision(self, tenant: TenantConfig) -> dict[str, str]:
        """Generate all config fragments for a tenant.

        Returns:
            Dict mapping filename → file content.
        """
        slug = tenant.tenant_id.lower().replace(" ", "-")
        files: dict[str, str] = {}

        # 1. ARI user config
        files[f"ari_{slug}.conf"] = self._render_ari_conf(tenant)

        # 2. PJSIP config (if trunk provided)
        if tenant.sip_trunk is not None:
            files[f"pjsip_{slug}.conf"] = self._render_pjsip_conf(tenant)

        # 3. Dialplan (extensions.conf fragment)
        files[f"extensions_{slug}.conf"] = self._render_extensions_conf(tenant)

        logger.info(
            "Provisioned tenant '%s': %d config files",
            tenant.tenant_id, len(files),
        )

        return files

    def write_files(self, files: dict[str, str]) -> list[Path]:
        """Write config fragments to the output directory.

        Creates the output directory if it doesn't exist.

        Returns:
            List of written file paths.
        """
        self.output_dir.mkdir(parents=True, exist_ok=True)
        paths: list[Path] = []

        for filename, content in files.items():
            path = self.output_dir / filename
            path.write_text(content)
            paths.append(path)
            logger.info("Wrote config: %s", path)

        return paths

    def deprovision(self, tenant_id: str) -> list[Path]:
        """Remove config fragments for a tenant.

        Returns:
            List of removed file paths.
        """
        slug = tenant_id.lower().replace(" ", "-")
        removed: list[Path] = []

        for prefix in ("ari_", "pjsip_", "extensions_"):
            path = self.output_dir / f"{prefix}{slug}.conf"
            if path.exists():
                path.unlink()
                removed.append(path)
                logger.info("Removed config: %s", path)

        return removed

    # ------------------------------------------------------------------
    # Live reload
    # ------------------------------------------------------------------

    DEFAULT_RELOAD_MODULES = (
        "res_pjsip.so",       # PJSIP endpoints / auth / aor / identify
        "pbx_config.so",      # extensions.conf dialplan
        "res_ari.so",         # ARI users
    )

    async def reload_asterisk(
        self,
        ari: ARIClient,
        modules: tuple[str, ...] | list[str] | None = None,
    ) -> list[str]:
        """Reload Asterisk so newly-written tenant configs take effect.

        Issues ``PUT /ari/asterisk/modules/{module}`` for each module
        whose config was touched. By default reloads the three modules
        we provision into: PJSIP, the dialplan, and ARI users.

        Args:
            ari: A connected :class:`~voxtra.ari.client.ARIClient`.
            modules: Optional override list. Defaults to
                :attr:`DEFAULT_RELOAD_MODULES`.

        Returns:
            The list of modules that reloaded successfully. Modules that
            failed to reload are logged at WARNING and omitted from the
            return value — provisioning never raises into the caller.
        """
        targets = tuple(modules) if modules is not None else self.DEFAULT_RELOAD_MODULES
        succeeded: list[str] = []
        for module in targets:
            try:
                await ari.reload_module(module)
                succeeded.append(module)
                logger.info("Reloaded Asterisk module: %s", module)
            except Exception as exc:
                logger.warning(
                    "Failed to reload Asterisk module %s: %s", module, exc,
                )
        return succeeded

    # ------------------------------------------------------------------
    # Config renderers
    # ------------------------------------------------------------------

    def _render_ari_conf(self, tenant: TenantConfig) -> str:
        """Render ari.conf fragment for a tenant's ARI user."""
        return (
            f"; Voxtra ARI user for tenant: {tenant.tenant_name}\n"
            f"; Auto-generated — do not edit manually\n"
            f"\n"
            f"[{tenant.ari_username}]\n"
            f"type = user\n"
            f"read_only = no\n"
            f"password = {tenant.ari_password}\n"
            f"password_format = plain\n"
        )

    def _render_pjsip_conf(self, tenant: TenantConfig) -> str:
        """Render pjsip.conf fragment for a tenant's SIP trunk."""
        trunk = tenant.sip_trunk
        if trunk is None:
            return ""

        slug = tenant.tenant_id.lower().replace(" ", "-")
        endpoint_name = f"voxtra-{slug}-trunk"
        codecs = "/".join(trunk.codecs) if trunk.codecs else "ulaw/alaw"

        lines = [
            f"; Voxtra SIP trunk for tenant: {tenant.tenant_name}",
            "; Auto-generated — do not edit manually",
            "",
            "; --- Transport ---",
            "",
            "; --- Auth ---",
            f"[{endpoint_name}-auth]",
            "type = auth",
            "auth_type = userpass",
            f"username = {trunk.username}",
            f"password = {trunk.password}",
            f"realm = {trunk.realm}",
            "",
            "; --- AOR ---",
            f"[{endpoint_name}-aor]",
            "type = aor",
            f"contact = sip:{trunk.host}:{trunk.port}",
            "qualify_frequency = 60",
            "",
            "; --- Endpoint ---",
            f"[{endpoint_name}]",
            "type = endpoint",
            f"transport = transport-{trunk.transport}",
            f"context = {tenant.context}",
            "disallow = all",
            f"allow = {codecs}",
            f"outbound_auth = {endpoint_name}-auth",
            f"aors = {endpoint_name}-aor",
            f"from_user = {trunk.username}",
            f"from_domain = {trunk.host}",
            "direct_media = no",
            "rtp_symmetric = yes",
            "force_rport = yes",
            "rewrite_contact = yes",
        ]

        if trunk.did:
            lines.append(f"callerid = {trunk.did}")

        if tenant.max_channels > 0:
            lines.extend([
                "",
                f"device_state_busy_at = {tenant.max_channels}",
            ])

        lines.extend([
            "",
            "; --- Registration ---",
            f"[{endpoint_name}-reg]",
            "type = registration",
            f"transport = transport-{trunk.transport}",
            f"outbound_auth = {endpoint_name}-auth",
            f"server_uri = sip:{trunk.host}:{trunk.port}",
            f"client_uri = sip:{trunk.username}@{trunk.host}:{trunk.port}",
            "retry_interval = 60",
            "expiration = 3600",
            "",
            "; --- Identify (match inbound by IP) ---",
            f"[{endpoint_name}-identify]",
            "type = identify",
            f"endpoint = {endpoint_name}",
            f"match = {trunk.host}",
        ])

        return "\n".join(lines) + "\n"

    def _render_extensions_conf(self, tenant: TenantConfig) -> str:
        """Render extensions.conf fragment for a tenant's dialplan."""
        slug = tenant.tenant_id.lower().replace(" ", "-")
        endpoint_name = f"voxtra-{slug}-trunk"

        lines = [
            f"; Voxtra dialplan for tenant: {tenant.tenant_name}",
            "; Auto-generated — do not edit manually",
            "",
            f"[{tenant.context}]",
            "; Inbound calls route to Stasis app",
            f"exten => _X.,1,NoOp(Voxtra inbound for tenant {slug})",
            f" same => n,Stasis({tenant.ari_app_name})",
            " same => n,Hangup()",
        ]

        # Add specific DID routing if configured
        for did in tenant.dids:
            clean_did = did.replace("+", "")
            lines.extend([
                "",
                f"exten => {clean_did},1,NoOp(Voxtra DID {did} for tenant {slug})",
                f" same => n,Stasis({tenant.ari_app_name})",
                " same => n,Hangup()",
            ])

        # Agent queue context for human handoff
        lines.extend([
            "",
            "; Agent queue context for human handoff",
            f"[voxtra-{slug}-queues]",
            f"exten => _X.,1,NoOp(Voxtra queue handoff for {slug})",
            " same => n,Queue(${EXTEN})",
            " same => n,Hangup()",
        ])

        # Outbound context
        if tenant.sip_trunk is not None:
            lines.extend([
                "",
                "; Outbound calls via trunk",
                f"[voxtra-{slug}-outbound]",
                f"exten => _+X.,1,NoOp(Voxtra outbound for {slug})",
                f" same => n,Dial(PJSIP/${{EXTEN}}@{endpoint_name},30)",
                " same => n,Hangup()",
                "",
                f"exten => _X.,1,NoOp(Voxtra outbound for {slug})",
                f" same => n,Dial(PJSIP/${{EXTEN}}@{endpoint_name},30)",
                " same => n,Hangup()",
            ])

        return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _generate_password(length: int = 32) -> str:
    """Generate a cryptographically secure random password."""
    alphabet = string.ascii_letters + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(length))
