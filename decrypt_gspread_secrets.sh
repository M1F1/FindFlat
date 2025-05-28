#!/bin/sh
# Decrypt the file
# --batch to prevent interactive command
# --yes to assume "yes" for questions
gpg --quiet --batch --yes --decrypt --passphrase="$GSPREAD_CREDENTIALS_PASSPHRASE" \
--output service_account.json service_account.json.gpg
