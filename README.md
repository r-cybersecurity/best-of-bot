# twitter_bot__r_cybersecurity

### hau 2 deploy

Build deployment package with `./build.sh`

Deploy via CLI:

```
aws lambda update-function-code --function-name MyLambdaFunction --zip-file fileb://deploy_me.zip
```

...or upload it in the UI