#!/usr/bin/env python3
"""Behaviour checks for the ticket source module. Run against a live app:

    python3 tools/test_api.py http://localhost:5173
"""
import json
import sys
import threading
import urllib.error
import urllib.request
import http.cookiejar

base = (sys.argv[1] if len(sys.argv) > 1 else 'http://localhost:5173').rstrip('/')
failures = []


class ApiClient:
    def __init__(self):
        self.csrf = ''
        self.cookies = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.cookies))

    def request(self, path, body=None, method=None, extra_headers=None):
        payload = None if body is None else json.dumps(body).encode()
        headers = {'Content-Type': 'application/json'}
        if self.csrf:
            headers['X-CSRF-Token'] = self.csrf
        if extra_headers:
            headers.update(extra_headers)
        request = urllib.request.Request(base + '/api' + path, data=payload, headers=headers, method=method)
        try:
            response = self.opener.open(request, timeout=20)
            return response.getcode(), json.load(response)
        except urllib.error.HTTPError as error:
            try:
                data = json.load(error)
            except Exception:
                data = {'raw': error.read().decode('utf-8', 'replace')}
            return error.code, data


def check(name, condition, detail=None):
    if condition:
        print('PASS:', name)
        return
    failures.append(name)
    print('FAIL:', name, detail if detail is not None else '', file=sys.stderr)


def error_payload(data):
    return isinstance(data, dict) and 'error' in data and 'message' in data


def main():
    anonymous = ApiClient()
    status, data = anonymous.request('/health')
    check('health', status == 200 and data.get('status') == 'ok' and str(data.get('php', '')).startswith('7.4.'), data)

    status, data = anonymous.request('/tickets')
    check('no session is 401 json', status == 401 and error_payload(data), (status, data))
    status, data = anonymous.request('/tickets/105/source', {'source_id': 2})
    check('unauthenticated change is 401 json', status == 401 and error_payload(data), (status, data))

    viewer = ApiClient()
    status, data = viewer.request('/demo/login', {'role': 'viewer'})
    check('viewer login', status == 200 and data.get('employee', {}).get('role') == 'viewer', data)
    viewer.csrf = data.get('csrf', '')

    editor = ApiClient()
    status, data = editor.request('/demo/login', {'role': 'editor'})
    check('editor login', status == 200 and data.get('employee', {}).get('role') == 'editor', data)
    editor.csrf = data.get('csrf', '')
    editor_id = data['employee']['id']
    editor_name = data['employee']['name']

    status, data = editor.request('/tickets/103')
    check(
        'ticket without source returns source null (original 500)',
        status == 200 and data.get('ticket', {}).get('id') == 103 and data['ticket']['source'] is None,
        (status, data),
    )

    status, data = editor.request('/tickets')
    tickets = {row['id']: row for row in data.get('tickets', [])} if status == 200 else {}
    check('list keeps null source_name', status == 200 and tickets.get(103, {}).get('source_name') is None, data)

    status, data = editor.request('/tickets/999')
    check('missing ticket is 404 json', status == 404 and error_payload(data), (status, data))

    before = editor.request('/tickets/105')
    status, data = viewer.request('/tickets/105/source', {'source_id': 2, 'employee_id': editor_id, 'permissions': ['FUNC_TICKETS_SOURCE_EDIT']})
    after = editor.request('/tickets/105')
    check(
        'viewer change is 403 and data is unchanged',
        status == 403 and error_payload(data) and after[1]['ticket']['source']['id'] == before[1]['ticket']['source']['id'] and len(after[1]['history']) == len(before[1]['history']),
        (status, data, after[1]),
    )

    before = editor.request('/tickets/104')
    status, data = editor.request('/tickets/104/source', {'source_id': 1})
    after = editor.request('/tickets/104')
    check(
        'archived ticket is 403 and data is unchanged',
        status == 403 and error_payload(data) and after[1]['ticket']['source']['id'] == 3 and len(after[1]['history']) == len(before[1]['history']),
        (status, data, after[1]),
    )

    before = editor.request('/tickets/105')
    current_source = before[1]['ticket']['source']['id']
    history_len = len(before[1]['history'])
    invalid_bodies = [
        {'source_id': '2'},
        {'source_id': 2.5},
        {'source_id': None},
        {},
        {'source_id': 0},
        {'source_id': -1},
        {'source_id': 999},
    ]
    invalid_ok = True
    details = []
    for body in invalid_bodies:
        status, data = editor.request('/tickets/105/source', body)
        after = editor.request('/tickets/105')
        ok = status == 400 and error_payload(data) and after[1]['ticket']['source']['id'] == current_source and len(after[1]['history']) == history_len
        if not ok:
            invalid_ok = False
            details.append((body, status, data, after[1]['ticket']))
    check('invalid source values are 400 without changes', invalid_ok, details)

    status, data = editor.request('/tickets/999/source', {'source_id': '2'})
    check('editor change of missing ticket is 404 before source validation', status == 404 and error_payload(data), (status, data))
    status, data = viewer.request('/tickets/999/source', {'source_id': 1})
    check('viewer is rejected before ticket lookup', status == 403 and error_payload(data), (status, data))

    start = editor.request('/tickets/105')
    current_id = start[1]['ticket']['source']['id']
    status, data = editor.request('/tickets/105/source', {'source_id': current_id})
    check(
        'same source succeeds without history row',
        status == 200 and data['ticket']['source']['id'] == current_id and len(data['history']) == len(start[1]['history']),
        (status, data),
    )

    old_id = 1
    new_id = 2
    editor.request('/tickets/105/source', {'source_id': old_id})
    before = editor.request('/tickets/105')
    status, data = editor.request('/tickets/105/source', {'source_id': new_id, 'employee_id': 1, 'employee_name': 'Анна Примерова'})
    history = data.get('history', [])
    latest = history[0] if history else {}
    check(
        'successful change is atomic and uses session employee',
        status == 200
        and data['ticket']['source']['id'] == new_id
        and len(history) == len(before[1]['history']) + 1
        and latest.get('employee_id') == editor_id
        and latest.get('employee_name') == editor_name
        and latest.get('old_source_id') == old_id
        and latest.get('new_source_id') == new_id
        and latest.get('created_at'),
        (status, data),
    )
    restore_status, restore = editor.request('/tickets/105/source', {'source_id': old_id})
    check('restore ticket 105 source', restore_status == 200 and restore['ticket']['source']['id'] == old_id, restore)

    results = {}

    def load(ticket_id):
        results[ticket_id] = editor.request('/tickets/%s' % ticket_id)

    first = threading.Thread(target=load, args=(101,))
    second = threading.Thread(target=load, args=(102,))
    first.start()
    second.start()
    first.join()
    second.join()
    check(
        'parallel ticket fetches keep matching payloads',
        results[101][0] == 200 and results[101][1]['ticket']['id'] == 101
        and results[102][0] == 200 and results[102][1]['ticket']['id'] == 102,
        results,
    )

    if failures:
        print('FAILED %s checks' % len(failures), file=sys.stderr)
        sys.exit(1)
    print('All behaviour checks passed')


if __name__ == '__main__':
    try:
        main()
    except (AssertionError, OSError, ValueError, KeyError) as error:
        print('FAIL:', str(error), file=sys.stderr)
        sys.exit(1)
