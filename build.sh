#!/bin/bash

# cleanup
rm -rf deploy_me.zip package

# install dependencies
pip install --target ./package requests tweepy typing_extensions Mastodon.py
pip install --no-deps --target ./package openai

# build zip with all data
cd package
zip -r ../deploy_me.zip .
cd ..
zip -g deploy_me.zip lambda_function.py
