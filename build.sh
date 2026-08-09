#!/bin/bash

# cleanup
rm -rf deploy_me.zip package

# install Lambda-compatible version of cryptography
pip install \
    --target ./package \
    --platform manylinux2014_x86_64 \
    --implementation cp \
    --python-version 3.12 \
    --only-binary=:all: --upgrade \
    "cryptography<42"

# install dependencies, cross-compiled for the Lambda Python 3.12 runtime so
# that compiled wheels (e.g. atproto's libipld C extension) match the runtime
pip install \
    --target ./package \
    --platform manylinux2014_x86_64 \
    --implementation cp \
    --python-version 3.12 \
    --only-binary=:all: \
    "urllib3>=1.26,<3" typing_extensions Mastodon.py atproto==0.0.34 distro praw jiter beautifulsoup4

# build zip with all data
cd package
zip -r ../deploy_me.zip .
cd ..
zip -g deploy_me.zip lambda_function.py
