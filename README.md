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

Then for each post, in descending order of priority, it checks in DynamoDB to see if there is a record of this being shared already. If there is, it skips to the next post. If there isn't, it builds the post and generates the summaries first, and only then claims the post in DynamoDB with a conditional write (so a stalled or failing LLM provider never permanently claims a post that was never actually shared). The claim carries a TTL of two weeks, so the bot automatically forgets what was posted after there's no more chance for it to appear in Reddit's hot posts list - keeping costs from ballooning. The conditional write enforces *at-most-once* posting: if two runs ever race on the same post, only the first to claim it can post it. We prefer that over at-least-once delivery, which could make duplicate posts - accepting that there may be cases where a claimed post is not actually shared on all platforms.

Once a post has been selected to promote on the "best of" bot accounts, a short summary is generated using an LLM (via OpenRouter, currently DeepSeek V4 Flash 0731, `deepseek/deepseek-v4-flash-0731`, routed to the cheapest provider serving it), written in a dry, deadpan, semi-professional voice and length-capped for each platform before posting. Each request is given a two-minute timeout, and if the model cannot produce a valid summary within the length limit after retries, the function errors out. Because summaries are generated before the post is claimed in DynamoDB, such a failure does not burn the post - it can simply be tried again on a later run. All posts are sanitized to remove hashtags and @ signs before posting to avoid tagging people, companies, etc.

Once a post has been made to each supported platform (or we've exhausted our retries for that platform), the Lambda function exits - and if no posts are made, it quits gracefully as well. For any errors encountered the function may try to gracefully continue, but if that is not possible it will error out, triggering SNS to ping the moderation staff to investigate the issue.

### Program Layout

To keep local testing straightforward, all application logic is in `lambda_function.py`. You can invoke it from your console as well for local testing. Without any credentials provided, it will show the current priority list for posting - but if needed, you can also save the required AWS, OpenRouter, and platform credentials to your environment to run it fully locally.

### Deployment Notes

Build deployment package with `./build.sh`, then deploy the resulting `deploy_me.zip` file via CLI or UI, for example:

```
aws lambda update-function-code --function-name twitter_bot__r_cybersecurity --zip-file fileb://deploy_me.zip
```

Core dependencies are pinned in `build.sh` for reproducible builds; the OpenRouter API key is provided to the Lambda function via the `OPENROUTER_API_KEY` environment variable.

### Considerations

Because this bot is oriented towards use in discussion-focused subreddits, it posts links directly to Reddit. When creating or running bots like this, it's important to be curteous to the communities you are posting to, so you do not spam them. For example, on Mastodon you should make posts unlisted so people can *choose to see* the bot's posts if they want to, but aren't spammed by the bot in public timelines.

This bot is not a great choice if you're looking to post content from subreddits that act more as link aggregators, such as r/netsec. For those, check out my other project [Bring Link Aggregator Subreddits to the Fediverse](https://github.com/tweedge/xpost-reddit-to-fediverse).
