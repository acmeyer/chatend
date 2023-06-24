# Create an AWS Backend with GPT

This is an experimental repository that uses OpenAI's API and AWS API to create a serverless backend based on the needs for your application.

**Note:** You should verify the code that is produced before using this in any real scenario or application. While it is impressive what it can create, it tends to hallucinate things and can produce code that might not do what you want.

## How to use

1. Clone this repository
2. Install the requirements with `pip install -r requirements.txt`
3. Run the script with `python main.py`

## Improvements

There are many improvements you could make to this. Please feel free to contribute any that you think of, here are a few ideas:

- Add database function for creation of a database and tables
- Integrate with other cloud providers, such as Azure and GCP
- Save messages and conversations to a database to keep track of state in between runs
