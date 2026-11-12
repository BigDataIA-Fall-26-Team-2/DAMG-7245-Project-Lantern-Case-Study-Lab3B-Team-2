"""Only authenticated, mandate-authorized messages can become standing rules."""
from datetime import datetime
import re
from creditwatch import channel, memory


def apply_correction(ws, scope, message, users, ledger):
    # Origin is derived from authentication, never accepted from a model argument.
    if channel.authority(message, users) != 'instruction':
        return memory.propose_write(scope, message['content'], 'untrusted', message.get('message_id'),
                                    ledger, ws / 'PRINCIPAL.md', ws / 'proposals', message['ts'][:10])
    channel.login(message['principal'], message['session_token'], scope, users)
    mid, content = message['message_id'], message['content']
    if not re.fullmatch(r'msg-[\w-]+', mid) or not content.strip() or '\n' in content or '\r' in content:
        raise ValueError('Correction must have a valid message ID and single-line content')
    day = datetime.fromisoformat(message['ts']).date().isoformat()
    path = ws / 'PRINCIPAL.md'
    line = f'- {content} ({mid}, {day})'
    text = path.read_text()
    existing = [s for s in text.splitlines() if re.search(r'\(' + re.escape(mid) + r', \d{4}-\d{2}-\d{2}\)$', s)]
    if existing:
        if existing != [line]:
            raise ValueError('Message ID already exists with different content')
        return 'already_written'
    return memory.propose_write(scope, content, 'principal', mid, ledger,
                                path, ws / 'proposals', day)
