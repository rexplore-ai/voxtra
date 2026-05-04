"""Tests for Voxtra tenant provisioning system."""

from __future__ import annotations

import tempfile
from pathlib import Path

from voxtra.provisioning.provisioner import TenantConfig, TenantProvisioner
from voxtra.types import SIPTrunk


class TestTenantConfig:
    def test_auto_generated_fields(self) -> None:
        config = TenantConfig(tenant_id="acme-corp")
        assert config.ari_app_name == "voxtra-acme-corp"
        assert config.ari_username == "voxtra-acme-corp"
        assert config.context == "voxtra-acme-corp-inbound"
        assert config.tenant_name == "acme-corp"
        assert len(config.ari_password) == 32

    def test_explicit_fields(self) -> None:
        config = TenantConfig(
            tenant_id="acme",
            ari_app_name="custom-app",
            ari_username="custom-user",
            ari_password="custom-pass",
            context="custom-ctx",
        )
        assert config.ari_app_name == "custom-app"
        assert config.ari_username == "custom-user"
        assert config.ari_password == "custom-pass"
        assert config.context == "custom-ctx"

    def test_with_sip_trunk(self) -> None:
        trunk = SIPTrunk(
            host="sip.carrier.com",
            username="user1",
            password="pass1",
            did="+265999123456",
        )
        config = TenantConfig(tenant_id="acme", sip_trunk=trunk)
        assert config.sip_trunk is not None
        assert config.sip_trunk.host == "sip.carrier.com"
        assert config.sip_trunk.realm == "sip.carrier.com"  # auto-set


class TestTenantProvisioner:
    def test_provision_generates_files(self) -> None:
        provisioner = TenantProvisioner(output_dir="/tmp/voxtra-test")
        tenant = TenantConfig(
            tenant_id="test-tenant",
            sip_trunk=SIPTrunk(host="sip.example.com", username="u", password="p"),
        )

        files = provisioner.provision(tenant)

        assert "ari_test-tenant.conf" in files
        assert "pjsip_test-tenant.conf" in files
        assert "extensions_test-tenant.conf" in files

    def test_provision_without_trunk_skips_pjsip(self) -> None:
        provisioner = TenantProvisioner(output_dir="/tmp/voxtra-test")
        tenant = TenantConfig(tenant_id="no-trunk")

        files = provisioner.provision(tenant)

        assert "ari_no-trunk.conf" in files
        assert "pjsip_no-trunk.conf" not in files
        assert "extensions_no-trunk.conf" in files

    def test_ari_conf_content(self) -> None:
        provisioner = TenantProvisioner(output_dir="/tmp/voxtra-test")
        tenant = TenantConfig(
            tenant_id="acme",
            ari_username="voxtra-acme",
            ari_password="test-password-123",
        )

        files = provisioner.provision(tenant)
        ari_conf = files["ari_acme.conf"]

        assert "[voxtra-acme]" in ari_conf
        assert "type = user" in ari_conf
        assert "password = test-password-123" in ari_conf

    def test_pjsip_conf_content(self) -> None:
        provisioner = TenantProvisioner(output_dir="/tmp/voxtra-test")
        trunk = SIPTrunk(
            host="sip.carrier.com",
            port=5060,
            username="acme_trunk",
            password="trunk_pass",
            did="+265999123456",
            codecs=["ulaw", "alaw"],
        )
        tenant = TenantConfig(tenant_id="acme", sip_trunk=trunk)

        files = provisioner.provision(tenant)
        pjsip = files["pjsip_acme.conf"]

        assert "[voxtra-acme-trunk-auth]" in pjsip
        assert "username = acme_trunk" in pjsip
        assert "[voxtra-acme-trunk-aor]" in pjsip
        assert "contact = sip:sip.carrier.com:5060" in pjsip
        assert "[voxtra-acme-trunk]" in pjsip
        assert "allow = ulaw/alaw" in pjsip
        assert "callerid = +265999123456" in pjsip

    def test_extensions_conf_content(self) -> None:
        provisioner = TenantProvisioner(output_dir="/tmp/voxtra-test")
        tenant = TenantConfig(
            tenant_id="acme",
            dids=["+265999123456"],
        )

        files = provisioner.provision(tenant)
        ext = files["extensions_acme.conf"]

        assert "[voxtra-acme-inbound]" in ext
        assert "Stasis(voxtra-acme)" in ext
        assert "265999123456" in ext  # DID without +

    def test_write_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            provisioner = TenantProvisioner(output_dir=tmpdir)
            tenant = TenantConfig(tenant_id="write-test")

            files = provisioner.provision(tenant)
            paths = provisioner.write_files(files)

            assert len(paths) >= 2
            for p in paths:
                assert p.exists()
                assert p.stat().st_size > 0

    def test_deprovision(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            provisioner = TenantProvisioner(output_dir=tmpdir)
            tenant = TenantConfig(
                tenant_id="remove-me",
                sip_trunk=SIPTrunk(host="sip.x.com", username="u", password="p"),
            )

            files = provisioner.provision(tenant)
            provisioner.write_files(files)

            # Verify files exist
            for filename in files:
                assert (Path(tmpdir) / filename).exists()

            # Deprovision
            removed = provisioner.deprovision("remove-me")
            assert len(removed) == 3

            # Verify files removed
            for filename in files:
                assert not (Path(tmpdir) / filename).exists()
