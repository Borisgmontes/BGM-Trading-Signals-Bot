"""Generate browser Push VAPID keys locally. Keep the private key secret."""
import base64
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives import serialization

def b64url(value):
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")

private = ec.generate_private_key(ec.SECP256R1())
private_pem = private.private_bytes(
    encoding=serialization.Encoding.PEM,
    format=serialization.PrivateFormat.PKCS8,
    encryption_algorithm=serialization.NoEncryption(),
)
public_raw = private.public_key().public_bytes(
    encoding=serialization.Encoding.X962,
    format=serialization.PublicFormat.UncompressedPoint,
)
print("VAPID_PUBLIC_KEY=" + b64url(public_raw))
print("VAPID_PRIVATE_KEY_PEM_BEGIN")
print(private_pem.decode("ascii"), end="")
print("VAPID_PRIVATE_KEY_PEM_END")
