#!/usr/bin/env python3
#-----------------------------------------------------------------------------#
#
# mock_ca.py — Mock Certificate Authority and Credential Provisioning
#
#   This script generates all credentials for the Infrastructure
#   Trust Plane proof of concept. Run it once before starting any
#   service. It produces four independent artifacts that serve
#   four independent trust relationships:
#
#   1. TLS CERTIFICATES (transport identity)
#      Files: ca.crt, ca.key, registry.crt/.key, cyrano.crt/.key
#
#      These prove transport identity: the server at this endpoint
#      is the server it claims to be. The A2A specification
#      requires HTTPS (Section 7.1) and recommends that clients
#      verify certificates against trusted TLS certificate
#      authorities (Section 7.2).
#
#      Demo: This script acts as a local TLS certificate authority,
#      issuing server certificates that all parties trust via the
#      local root (ca.crt). In production, a commercial TLS
#      TLS certificate authority (Let's Encrypt, DigiCert, Google Trust
#      Services) issues these certificates. The mock TLS CA is the
#      one component in this system that does not exist in
#      production. Everything else is the real protocol.
#
#   2. TRUST BADGE (agent service identity — agent to Registry)
#      Files: cyrano_trust_badge.txt, cyrano_trust_badge_hash.txt
#      Also updates: registry/agents.json (trust_badge_hash field)
#
#      A shared secret between Cyrano and the Agent Registry.
#      Cyrano presents the raw badge during pairing; the Registry
#      compares its SHA-256 hash against the stored value. The
#      Trust Badge proves agent service identity: OSU authorized this
#      agent. It has no cryptographic relationship to TLS.
#
#      Demo: Generated here as a random hex string for convenience.
#      In production, an administrative provisioning process
#      controlled by OSU generates Trust Badges when agents are
#      registered. Agent provisioning is separate from TLS
#      certificate issuance: different authority, different
#      channel, different lifecycle.
#
#   3. HMAC SIGNING KEY (assertion verification — Registry to Chris)
#      File: registry_signing.key
#
#      A symmetric key shared between the Registry and Chris. The
#      Registry signs pairing assertions with it; Chris verifies
#      signatures. It has no cryptographic relationship to TLS
#      certificates or to Trust Badges.
#
#      Demo: Generated here as a random hex string and shared via
#      file. In production, this becomes an asymmetric key pair
#      (RS256 or Ed25519): the Registry holds the private signing
#      key; Chris holds the public verification key. The public
#      key can be distributed openly. This is a key management
#      change, not an architectural one.
#
#   4. CHRIS CREDENTIAL (initiator identity — Chris to Registry)
#      Files: chris_credential.txt, chris_credential_hash.txt
#      Also updates: registry/agents.json (chris-001 record)
#
#      A shared secret between Chris and the Agent Registry.
#      Chris presents it with every request to the AR. The AR
#      hashes it and compares against the stored value.
#
#      This credential guards against a Fake Chris exploiting
#      the network boundary between Chris and the AR. The
#      Chris-AR trust is organizational (the admin team controls
#      both), but the credential makes that trust verifiable at
#      the protocol level.
#
#      Deliberately not called a Trust Badge. Trust Badges are
#      user-facing earned trust from external teams; Chris's
#      credential is infrastructure authentication that users
#      never see. Different trust tiers get different names.
#
#      Demo: Generated as a random hex string, same as the Trust
#      Badge. In production, provisioned through the admin team's
#      internal process.
#
#   All four artifacts are generated in one script for demo
#   convenience. In production, each would come from a different
#   issuing authority through a different process.
#
#   Output goes to certs/ at the repo root. The directory is
#   gitignored because it contains private keys.
#
# Usage:
#   python3 scripts/mock_ca.py
#
#-----------------------------------------------------------------------------#

import datetime
import hashlib
import ipaddress
import logging
import os
import secrets
import sys

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

#-----------------------------------------------------------------------------#

logging.basicConfig(level=logging.INFO, stream=sys.stderr)
logger = logging.getLogger(__name__)

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CERTS_DIR = os.path.join(REPO_ROOT, "certs")

CA_VALIDITY_DAYS = 365
SERVER_VALIDITY_DAYS = 365

#-----------------------------------------------------------------------------#
#
# generate_ca()
#   Create a self-signed root TLS certificate authority and its
#   private key.
#
#   This is the mock TLS certificate authority: the one component
#   that does not exist in production. In production, commercial
#   TLS certificate authorities (Let's Encrypt, DigiCert, etc.)
#   fill this role. The mock TLS CA exists so the demo follows
#   the correct TLS verification path (client checks cert, cert
#   chains to trusted root) rather than skipping verification.
#
#   Every client (Chris, Cyrano when calling the Registry) trusts
#   ca.crt. Every server (Registry, Cyrano) presents a certificate
#   signed by this TLS CA.
#
#   Returns:
#       tuple: (ca_key, ca_cert) -- the private key and certificate.
#
#-----------------------------------------------------------------------------#

def generate_ca() -> tuple:
    ca_key = rsa.generate_private_key(
        public_exponent=65537,
        key_size=2048,
    )

    ca_name = x509.Name([
        x509.NameAttribute(
            NameOID.COMMON_NAME, "OpenBeavs Dev CA"
        ),
        x509.NameAttribute(
            NameOID.ORGANIZATION_NAME, "OpenBeavs Development"
        ),
    ])

    now = datetime.datetime.now(datetime.timezone.utc)
    ca_cert = (
        x509.CertificateBuilder()
        .subject_name(ca_name)
        .issuer_name(ca_name)
        .public_key(ca_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now)
        .not_valid_after(now + datetime.timedelta(days=CA_VALIDITY_DAYS))
        .add_extension(
            x509.BasicConstraints(ca=True, path_length=0),
            critical=True,
        )
        .add_extension(
            x509.KeyUsage(
                digital_signature=False,
                key_cert_sign=True,
                crl_sign=True,
                content_commitment=False,
                key_encipherment=False,
                data_encipherment=False,
                key_agreement=False,
                encipher_only=False,
                decipher_only=False,
            ),
            critical=True,
        )
        .add_extension(
            x509.SubjectKeyIdentifier.from_public_key(
                ca_key.public_key()
            ),
            critical=False,
        )
        .sign(ca_key, hashes.SHA256())
    )

    return ca_key, ca_cert


#-----------------------------------------------------------------------------#
#
# generate_server_cert()
#   Create a server TLS certificate signed by the mock TLS CA.
#
#   Each server (Registry, Cyrano) gets its own certificate with
#   SANs for localhost and 127.0.0.1. In production, a commercial
#   TLS certificate authority would issue these with SANs matching
#   real domain names. Separate certs maintain the correct trust
#   model: in production these would be different hosts.
#
#   Args:
#       ca_key: The TLS CA's private key (signs the new cert).
#       ca_cert: The TLS CA's certificate (provides issuer name).
#       cn (str): Common Name for the server certificate.
#
#   Returns:
#       tuple: (server_key, server_cert).
#
#-----------------------------------------------------------------------------#

def generate_server_cert(ca_key, ca_cert, cn: str) -> tuple:
    server_key = rsa.generate_private_key(
        public_exponent=65537,
        key_size=2048,
    )

    server_name = x509.Name([
        x509.NameAttribute(NameOID.COMMON_NAME, cn),
    ])

    now = datetime.datetime.now(datetime.timezone.utc)
    server_cert = (
        x509.CertificateBuilder()
        .subject_name(server_name)
        .issuer_name(ca_cert.subject)
        .public_key(server_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now)
        .not_valid_after(
            now + datetime.timedelta(days=SERVER_VALIDITY_DAYS)
        )
        .add_extension(
            x509.SubjectAlternativeName([
                x509.DNSName("localhost"),
                x509.IPAddress(ipaddress.IPv4Address("127.0.0.1")),
            ]),
            critical=False,
        )
        .add_extension(
            x509.BasicConstraints(ca=False, path_length=None),
            critical=True,
        )
        .add_extension(
            x509.AuthorityKeyIdentifier.from_issuer_public_key(
                ca_key.public_key()
            ),
            critical=False,
        )
        .add_extension(
            x509.SubjectKeyIdentifier.from_public_key(
                server_key.public_key()
            ),
            critical=False,
        )
        .sign(ca_key, hashes.SHA256())
    )

    return server_key, server_cert


#-----------------------------------------------------------------------------#
#
# write_pem()
#   Write a private key or certificate to a PEM file.
#
#   Private keys are written unencrypted. This is acceptable for
#   local development credentials that live in a gitignored
#   directory. Production keys would be encrypted or managed by
#   a secrets store.
#
#   Args:
#       path (str): Destination file path.
#       obj: A cryptography key or certificate object.
#
#-----------------------------------------------------------------------------#

def write_pem(path: str, obj) -> None:
    if isinstance(obj, rsa.RSAPrivateKey):
        data = obj.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.TraditionalOpenSSL,
            encryption_algorithm=serialization.NoEncryption(),
        )
    else:
        data = obj.public_bytes(serialization.Encoding.PEM)

    with open(path, "wb") as f:
        f.write(data)

    logger.info("  wrote %s", os.path.relpath(path, REPO_ROOT))


#-----------------------------------------------------------------------------#
#
# generate_trust_credentials()
#   Generate the pairing protocol credentials. These are
#   independent of TLS certificates and of each other.
#
#   1. Trust Badge — a 32-byte random hex string shared between
#      Cyrano and the Agent Registry. The Registry stores a
#      SHA-256 hash in agents.json; Cyrano holds the raw value.
#      In production, an OSU administrative provisioning process
#      generates and distributes Trust Badges when agents are
#      registered. Here, we generate it alongside TLS certs
#      for demo convenience only.
#
#   2. HMAC signing key — a 32-byte random hex string shared
#      between the Registry and Chris. The Registry signs pairing
#      assertions; Chris verifies them. In production, this
#      becomes an asymmetric key pair (RS256 or Ed25519) so the
#      verification key can be public. Here, we use symmetric
#      HMAC because it is simpler to set up for a demo.
#
#   3. Chris credential — a 32-byte random hex string shared
#      between Chris and the Agent Registry. Chris presents the
#      raw value; the Registry compares its SHA-256 hash. In
#      production, the admin team provisions this through an
#      internal process.
#
#   All three are written as plain text files in certs/.
#
#-----------------------------------------------------------------------------#

def generate_trust_credentials() -> None:
    trust_badge = secrets.token_hex(32)
    badge_hash = hashlib.sha256(trust_badge.encode()).hexdigest()

    badge_path = os.path.join(CERTS_DIR, "cyrano_trust_badge.txt")
    with open(badge_path, "w") as f:
        f.write(trust_badge)
    logger.info("  wrote %s", os.path.relpath(badge_path, REPO_ROOT))

    hash_path = os.path.join(CERTS_DIR, "cyrano_trust_badge_hash.txt")
    with open(hash_path, "w") as f:
        f.write(badge_hash)
    logger.info("  wrote %s", os.path.relpath(hash_path, REPO_ROOT))

    signing_key = secrets.token_hex(32)
    key_path = os.path.join(CERTS_DIR, "registry_signing.key")
    with open(key_path, "w") as f:
        f.write(signing_key)
    logger.info("  wrote %s", os.path.relpath(key_path, REPO_ROOT))

    chris_credential = secrets.token_hex(32)
    chris_hash = hashlib.sha256(
        chris_credential.encode()
    ).hexdigest()

    chris_path = os.path.join(
        CERTS_DIR, "chris_credential.txt"
    )
    with open(chris_path, "w") as f:
        f.write(chris_credential)
    logger.info(
        "  wrote %s", os.path.relpath(chris_path, REPO_ROOT)
    )

    chris_hash_path = os.path.join(
        CERTS_DIR, "chris_credential_hash.txt"
    )
    with open(chris_hash_path, "w") as f:
        f.write(chris_hash)
    logger.info(
        "  wrote %s",
        os.path.relpath(chris_hash_path, REPO_ROOT),
    )

    _update_agents_json(badge_hash, chris_hash)


#-----------------------------------------------------------------------------#
#
# _update_agents_json()
#   Write credential hashes into registry/agents.json so the
#   Registry and the generated credentials stay in sync. Without
#   this, the operator would need to copy hashes manually after
#   every cert regeneration -- an easy step to forget and a
#   confusing failure to debug.
#
#   Writes the full schema: agent records (type "agent") with
#   trust_badge_hash, and the Chris client record (type "client")
#   with chris_credential_hash. The type field distinguishes agents
#   from clients in a single flat namespace.
#
#   Args:
#       badge_hash (str): SHA-256 hex digest of the Trust Badge.
#       chris_credential_hash (str): SHA-256 hex digest of the
#           Chris credential.
#
#-----------------------------------------------------------------------------#

def _update_agents_json(
    badge_hash: str, chris_credential_hash: str
) -> None:
    import json

    agents_path = os.path.join(
        REPO_ROOT, "registry", "agents.json"
    )

    data = {
        "cyrano-001": {
            "type": "agent",
            "name": "Cyrano de Bergerac",
            "endpoint": "https://localhost:8002",
            "status": "approved",
            "trust_badge_hash": badge_hash,
        },
        "chris-001": {
            "type": "client",
            "name": "Chris (CLI)",
            "chris_credential_hash": chris_credential_hash,
        },
    }

    with open(agents_path, "w") as f:
        json.dump(data, f, indent=2)
        f.write("\n")

    logger.info(
        "  wrote %s",
        os.path.relpath(agents_path, REPO_ROOT),
    )


#-----------------------------------------------------------------------------#
#
# main()
#   Entry point. Generates all certificates and trust credentials.
#
#-----------------------------------------------------------------------------#

def main() -> None:
    if os.path.exists(CERTS_DIR):
        logger.error(
            "certs/ already exists. Remove it first to regenerate."
        )
        sys.exit(1)

    os.makedirs(CERTS_DIR)

    # Artifact 1 of 3: TLS certificates (transport identity).
    # In production, a commercial TLS certificate authority issues these.
    logger.info("generating mock TLS CA and server certificates")

    ca_key, ca_cert = generate_ca()
    write_pem(os.path.join(CERTS_DIR, "ca.key"), ca_key)
    write_pem(os.path.join(CERTS_DIR, "ca.crt"), ca_cert)

    logger.info("generating Registry TLS server certificate")
    reg_key, reg_cert = generate_server_cert(
        ca_key, ca_cert, "OpenBeavs Registry"
    )
    write_pem(os.path.join(CERTS_DIR, "registry.key"), reg_key)
    write_pem(os.path.join(CERTS_DIR, "registry.crt"), reg_cert)

    logger.info("generating Cyrano TLS server certificate")
    cyr_key, cyr_cert = generate_server_cert(
        ca_key, ca_cert, "Cyrano"
    )
    write_pem(os.path.join(CERTS_DIR, "cyrano.key"), cyr_key)
    write_pem(os.path.join(CERTS_DIR, "cyrano.crt"), cyr_cert)

    # Artifacts 2--4: Trust Badge (agent service identity), HMAC
    # signing key (assertion verification), and Chris credential
    # (initiator identity). All are independent of TLS and of
    # each other. In production, each comes from a different
    # provisioning process.
    logger.info("generating trust credentials (independent of TLS)")
    generate_trust_credentials()

    logger.info("done. certs/ contains:")
    for name in sorted(os.listdir(CERTS_DIR)):
        logger.info("  %s", name)


if __name__ == "__main__":
    main()

#-----------------------------------------------------------------------------#
#eof#
