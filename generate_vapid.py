"""Generate browser Push VAPID keys locally. Keep the private key secret."""
import base64
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives import serialization

def b64url(value):
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")

private = ec.generate_private_key(ec.SECP256R1())
private_raw = private.private_numbers().private_value.to_bytes(32, "big")
public_raw = private.public_key().public_bytes(
    encoding=serialization.Encoding.X962,
    format=serialization.PublicFormat.UncompressedPoint,
)
print("VAPID_PUBLIC_KEY=" + b64url(public_raw))
print("VAPID_PRIVATE_KEY=" + b64url(private_raw))
