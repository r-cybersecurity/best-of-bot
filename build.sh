#!/bin/bash

# cleanup
rm -rf deploy_me.zip package

# install dependencies
pip install --target ./package urllib3==1.26.0 requests tweepy typing_extensions Mastodon.py atprototools
pip install --no-deps --target ./package openai

# build zip with all data
cd package
zip -r ../deploy_me.zip .
cd ..
zip -g deploy_me.zip lambda_function.py
