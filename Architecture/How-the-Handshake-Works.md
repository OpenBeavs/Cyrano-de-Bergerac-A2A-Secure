# How the Handshake Works

This document explains the trust handshake between Chris and Cyrano, mediated by the Agent Registry (AR). The handshake runs over the A2A transport (HTTPS/JSON-RPC) after the TLS connection is established but before any user messages flow. It establishes that the server Chris is talking to is genuinely the agent the Registry authorized. No user payload is sent until pairing completes successfully.

## Step 1: Chris queries the Registry for the agent

Chris holds an agent ID (e.g., "cyrano-001"). Chris queries the Registry for that ID. The Registry returns the agent's record: its name, its endpoint URL, and its trust status. If the agent doesn't exist or isn't approved, Chris aborts.

## Step 2: Chris requests a challenge token

Chris requests a challenge from the Registry for that agent ID. The Registry generates a random, short-lived token (64 hex characters via `secrets.token_hex`), stores it in memory bound to the agent ID with a 60-second TTL, and returns it. The challenge token is a plain random value, not signed. Its security comes from the fact that it lives only in the Registry's memory: Cyrano must present it back to the Registry at `/pairing/verify` to prove it received it from a legitimate pairing flow. The signing happens later, on the pairing assertion (Step 5), not on the challenge token.

## Step 3: Chris sends the challenge to Cyrano

Chris sends the challenge token to Cyrano's `/pairing/respond` endpoint over the established TLS connection. This is a pairing-protocol message, not a user conversation message. No user payload has been sent at this point.

## Step 4: Cyrano responds with the challenge and its Trust Badge

Cyrano sends the challenge token to the Registry along with its Trust Badge (a shared secret known only to Cyrano and the Registry). The Registry validates three conditions: the badge matches the stored credential for cyrano-001, the challenge token was issued by the Registry and has not expired, and the agent's trust status is still approved.

## Step 5: The Registry issues a pairing assertion

If all three conditions pass, the Registry signs a short-lived pairing assertion containing the agent ID, the Registry's signature, and an expiration timestamp. The Registry returns this assertion to Cyrano.

## Step 6: Cyrano returns the assertion to Chris

Cyrano forwards the signed assertion to Chris. Chris verifies the signature using a key shared with the Registry, confirms the assertion contains the expected agent ID, and confirms the assertion has not expired.

If all checks pass, pairing is complete. Chris has cryptographic proof that the endpoint is the cyrano-001 authorized by the Registry. Chris begins routing user messages.

## Trust property

The Trust Badge never leaves the Cyrano-Registry channel. Chris validates the Registry's signature, not Cyrano's secret. Because the Registry mediates, neither Chris nor Cyrano needs to disclose its credentials to the other.
