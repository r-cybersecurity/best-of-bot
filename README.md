# r/cybersecurity Twitter Bot

[![License](https://img.shields.io/github/license/r-cybersecurity/twitter_bot__r_cybersecurity)](https://github.com/r-cybersecurity/twitter_bot__r_cybersecurity)
[![Code Style](https://img.shields.io/badge/code%20style-black-black)](https://github.com/psf/black)

This bot reads the 25 most popular tweets from [r/cybersecurity](https://reddit.com/r/cybersecurity), applies some logic to prioritize and filter them (by topic, number of comments, karma, and karma ratio), and then posts the results to Twitter via [Tweepy](https://www.tweepy.org/). This creates an approximate list of the "best of r/cybersecurity" posts.

This follows a philosophy of "less is more" - some days there are only a handful of great posts/great discussions, and we'd prefer *not* to tweet if it may be a quieter day on the subreddit.

### How Does it Work?

The contents of this repository are an AWS Lambda function. The Lambda function is called by EventBridge every hour, to check the top posts on the subreddit. It then prioritizes and filters them with the aforementioned checks.

Then for each post, in descending order of priority, it checks in DynamoDB to see if there is a record of this being tweeted already. If it was, it skips to the next post. If it wasn't, it adds an entry to DynamoDB stating what is being posted, with a TTL of two weeks (so we automatically forget what was posted after there's no more chance for it to appear in Reddit's hot posts list - keeping costs from ballooning). The choices made in the DynamoDB logic ensure that this bot will post *at-most-once* - there may be cases where a tweet is saved to DynamoDB, but is not actually tweeted. We prefer that instead of at-least-once delivery (which could make duplicate tweets).

Once a tweet has been made, the Lambda function exits cleanly - and if no tweets are made, it quits gracefully as well. For any errors encountered the function may try to gracefully continue, but if that is not possible it will error out, triggering SNS to ping the moderation staff to investigate the issue.

The total ongoing cost of this bot is currently estimated to be $0.02/mo - so don't worry about bankrupting us mods!

### Program Layout

To keep local testing straightforward, all application logic is in `lambda_function.py`. You can invoke it from your console as well for local testing. Without any credentials provided, it will show the current priority list for posting - but if needed, you can also save the required AWS and Tweepy credentials to your environment to run it fully locally.

### Deployment Notes

Build deployment package with `./build.sh`, then deploy the resulting `deploy_me.zip` file via CLI or UI, for example:

```
aws lambda update-function-code --function-name twitter_bot__r_cybersecurity --zip-file fileb://deploy_me.zip
```

Yes, the dependencies aren't pinned. No, this isn't automated and probably could be. It's a Twitter bot - not a production application - and was written to be "good enough" in six hours, give or take. I do enough productionizing at work :P
