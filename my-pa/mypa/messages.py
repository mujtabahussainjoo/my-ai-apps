"""Validation for local agent conversation input."""
def validate_messages(messages):
    if not isinstance(messages, list) or not messages or len(messages) > 200:
        raise ValueError('Provide 1–200 chat messages')
    for message in messages:
        if not isinstance(message, dict) or message.get('role') not in ('system', 'user', 'assistant') or not isinstance(message.get('content'), str) or not message['content'].strip():
            raise ValueError('Each message needs a valid role and nonempty text content')
    if messages[-1]['role'] != 'user':
        raise ValueError('The last message must be from the user')

