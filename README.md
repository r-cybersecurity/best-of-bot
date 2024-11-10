# "Best Of" r/cybersecurity Bot

[![License](https://img.shields.io/github/license/r-cybersecurity/best-of-bot)](https://github.com/r-cybersecurity/best-of-bot)
[![Code Style](https://img.shields.io/badge/code%20style-black-black)](https://github.com/psf/black)

This bot reads the 25 most popular posts from [r/cybersecurity](https://reddit.com/r/cybersecurity), applies some logic to prioritize and filter them (by topic, number of comments, karma, and karma ratio), selects a unique and not-yet-posted thread, summarizes the post, and then posts the summary+link to supported platforms. This creates an approximate list of the "best of r/cybersecurity" posts.

This follows a philosophy of "less is more" - some days there are only a handful of great posts/great discussions, and we'd prefer *not* to promote a less-exciting post if it may be a quieter day on the subreddit.

Best of r/cybersecurity bots can be found on the following platforms:

* Mastodon: [@r_cybersecurity@infosec.exchange](https://infosec.exchange/@r_cybersecurity)
* Bluesky: [@cybersecurity.page](https://bsky.app/profile/cybersecurity.page)

Our Twitter bot was killed due to [Twitter's recent API changes](https://mashable.com/article/twitter-good-bot-purge-makeitaquote-hourly-animal-accounts), and we will not return to the platform. For those that followed the bot there, you will need to find another platform to follow the bot on.

### How Does it Work?

The contents of this repository are an AWS Lambda function. The Lambda function is called by EventBridge every hour, to check the top posts on the subreddit. It then prioritizes and filters them with the aforementioned checks.

Then for each post, in descending order of priority, it checks in DynamoDB to see if there is a record of this being shared already. If it was, it skips to the next post. If it wasn't, it adds an entry to DynamoDB stating what is being posted, with a TTL of two weeks (so we automatically forget what was posted after there's no more chance for it to appear in Reddit's hot posts list - keeping costs from ballooning). The choices made in the DynamoDB logic ensure that this bot will post *at-most-once* - there may be cases where a shared post is saved to DynamoDB, but is not actually shared on all platforms. We prefer that instead of at-least-once delivery (which could make duplicate posts).

Once a post has been selected to promote on the "best of" bot accounts, a short summary is generated using OpenAI's GPT-3.5-Turbo model, allowing people to know what they're clicking on from other platforms (and boost relevance, searchability, etc. of the bot itself). If the summary is too long for certain platforms, it will fall back to the post title for those platforms only; if the post title is too long, it will fall back to just posting the link. All posts are sanitized to remove hashtags and @ signs before posting to avoid tagging people, companies, etc.

Once a post has been made to each supported platform (of we've exhausted our retries for that platform), the Lambda function exits - and if no posts are made, it quits gracefully as well. For any errors encountered the function may try to gracefully continue, but if that is not possible it will error out, triggering SNS to ping the moderation staff to investigate the issue.

### Program Layout

To keep local testing straightforward, all application logic is in `lambda_function.py`. You can invoke it from your console as well for local testing. Without any credentials provided, it will show the current priority list for posting - but if needed, you can also save the required AWS, OpenAI, and Tweepy credentials to your environment to run it fully locally.

### Deployment Notes

Build deployment package with `./build.sh`, then deploy the resulting `deploy_me.zip` file via CLI or UI, for example:

```
aws lambda update-function-code --function-name twitter_bot__r_cybersecurity --zip-file fileb://deploy_me.zip
```

Yes, the dependencies aren't pinned. No, this isn't automated and probably could be. It's a Twitter bot which is updated almost-never and has very little access to anything (worst thing is probably my OpenAI key), so it doesn't *really* matter.

### Considerations

Because this bot is oriented towards use in discussion-focused subreddits, it posts links directly to Reddit. When creating or running bots like this, it's important to be curteous to the communities you are posting to, so you do not spam them. For example, on Mastodon you should make posts unlisted so people can *choose to see* the bot's posts if they want to, but aren't spammed by the bot in public timelines.

This bot is not a great choice if you're looking to post content from subreddits that act more as link aggregators, such as r/netsec. For those, check out my other project [Bring Link Aggregator Subreddits to the Fediverse](https://github.com/tweedge/xpost-reddit-to-fediverse).
