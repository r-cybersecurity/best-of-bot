#!/bin/bash

# cleanup
rm -rf deploy_me.zip package

# install dependencies
pip install --target ./package requests tweepy typing_extensions
pip install --no-deps --target ./package openai

# build zip with all data
cd package
zip -r ../deploy_me.zip .
cd ..
zip -g deploy_me.zip lambda_function.py
zip -g deploy_me.zip permitted_hashtags.json