"""Ein VAPID-Schlüsselpaar erzeugen.

    uv run python -m scripts.vapid_schluessel

VAPID („Voluntary Application Server Identification") ist der Ausweis unseres
Servers gegenüber den Push-Diensten von Apple, Google und Mozilla. Ohne ihn
nehmen die keine Nachricht an.

Das Schlüsselpaar erzeugst du **einmal** und behältst es. Wirfst du es weg und
machst ein neues, sind alle bestehenden Subscriptions wertlos — jedes Gerät
müsste erneut abonnieren.

Anders als bei Apple kostet das nichts und dauert eine Sekunde.
"""

import base64

from py_vapid import Vapid01


def _base64url(rohdaten: bytes) -> str:
    """Ohne `=`-Auffüllzeichen — so verlangt es der Web-Push-Standard."""
    return base64.urlsafe_b64encode(rohdaten).rstrip(b"=").decode("ascii")


def main() -> None:
    vapid = Vapid01()
    vapid.generate_keys()

    if vapid.private_key is None or vapid.public_key is None:
        raise SystemExit("Schlüsselerzeugung fehlgeschlagen.")

    # Der private Schlüssel als roher Zahlenwert (32 Byte), der öffentliche im
    # unkomprimierten Punktformat (65 Byte). Genau diese beiden Formen
    # erwarten `pywebpush` bzw. die Browser-API.
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

    privat = _base64url(vapid.private_key.private_numbers().private_value.to_bytes(32, "big"))
    oeffentlich = _base64url(
        vapid.public_key.public_bytes(Encoding.X962, PublicFormat.UncompressedPoint)
    )
    assert isinstance(vapid.private_key.curve, ec.SECP256R1)  # P-256, wie vom Standard verlangt

    print("Fertig. Diese zwei Zeilen in backend/.env eintragen:\n")
    print(f"VAPID_PUBLIC_KEY={oeffentlich}")
    print(f"VAPID_PRIVATE_KEY={privat}")
    print("\nUnd den öffentlichen Schlüssel braucht sonst niemand von Hand —")
    print("der Browser holt ihn sich über GET /push/config.")
    print("\n⚠️  .env ist gitignored. Der private Schlüssel gehört nie ins Repository.")


if __name__ == "__main__":
    main()
