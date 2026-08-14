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
    "cryptography==41.0.7"

# install dependencies, cross-compiled for the Lambda Python 3.12 runtime so
# that compiled wheels (e.g. atproto's libipld C extension) match the runtime.
# Core dependencies are pinned exactly for reproducible builds; transitive
# dependencies are resolved by pip. atproto must be >=0.0.60 to tolerate
# httpx 0.28.1, which the openrouter SDK requires.
pip install \
    --target ./package \
    --platform manylinux2014_x86_64 \
    --implementation cp \
    --python-version 3.12 \
    --only-binary=:all: \
    "urllib3==2.7.0" \
    "typing_extensions==4.16.0" \
    "Mastodon.py==2.2.2" \
    "atproto==0.0.69" \
    "distro==1.9.0" \
    "praw==8.0.3" \
    "jiter==0.16.0" \
    "beautifulsoup4==4.15.0" \
    "openrouter==1.1.57"

# build zip with all data
cd package
zip -r ../deploy_me.zip .
cd ..
zip -g deploy_me.zip lambda_function.py
