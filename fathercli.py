#!/bin/python3
import argparse
import asyncio
import json
import logging
import re
import sys

from async_generator import async_generator, aclosing, yield_
from telethon import events
from telethon.sync import TelegramClient
from telethon.tl import types

logging.basicConfig(level=logging.WARNING)

FATHER = 'BotFather'
NEXT = chr(187)

NO_BOTS_MESSAGE = 'You have currently no bots'
MAX_BOTS_MESSAGE = 'That I cannot do.'


class Config:
    config_name = 'fathercli.json'
    session_name = 'fathercli'

    def __init__(self):
        try:
            with open(self.config_name) as f:
                self.__dict__ = json.load(f)
        except OSError:
            self.api_id = 0
            self.api_hash = ''
            self.bots = []

    def save(self):
        with open(self.config_name, 'w', encoding='utf-8') as f:
            json.dump(self.__dict__, f)

    def __setattr__(self, key, value):
        super().__setattr__(key, value)
        self.save()


def eprint(*args, **kwargs):
    print(*args, file=sys.stderr, **kwargs)
    quit(1)


def find_bot(config, query):
    clean = re.compile(r'[@\s]|(_?bot)$', re.IGNORECASE)
    q = clean.sub('', query).lower()
    for bot_id, bot_username in config.bots:
        bot_username = clean.sub('', bot_username).lower()
        if q in (str(bot_id), bot_username):
            return bot_id

    eprint('No bot found for ', q)


async def await_event(client, event, pre):
    message = asyncio.Future()

    @client.on(event)
    async def handler(ev):
        message.set_result(ev.message)

    await pre
    message = await message
    client.remove_event_handler(handler)
    return message


@async_generator
async def iter_buttons(client):
    message = await await_event(
        client,
        events.NewMessage(FATHER),
        client.send_message(FATHER, '/mybots')
    )

    done = not message.buttons
    while not done:
        done = True
        for row in message.buttons:
            for button in row:
                if button.text.startswith('@'):
                    await yield_(button)
                elif button.text == NEXT:
                    done = False
                    message = await await_event(
                        client,
                        events.MessageEdited(FATHER),
                        button.click()
                    )


def get_bot_id(button):
    return int(button.data[button.data.index(b'/') + 1:])


async def load_bots(client):
    bots = []
    async with aclosing(iter_buttons(client)) as it:
        async for button in it:
            bots.append((get_bot_id(button), button.text))

    return bots


async def get_bot_menu(client, bot_id):
    async with aclosing(iter_buttons(client)) as it:
        async for button in it:
            if get_bot_id(button) == bot_id:
                return await await_event(
                    client,
                    events.MessageEdited(FATHER),
                    pre=button.click()
                )
        else:
            eprint('No bot with ID', bot_id, 'found')


async def get_token(client, bot_id, revoke=True):
    path = 'bots/{}/tokn'.format(bot_id).encode('ascii')
    message = await get_bot_menu(client, bot_id)
    message = await await_event(
        client,
        events.MessageEdited(FATHER),
        pre=message.click(data=path)
    )
    if revoke:
        message = await await_event(
            client,
            events.MessageEdited(FATHER),
            pre=message.click(data=path + b'/revoke')
        )

    for entity, text in message.get_entities_text():
        if isinstance(entity, types.MessageEntityCode):
            return text

    eprint('Failed to retrieve token for bot', bot_id)


async def create_bot(client, name):
    if '@' not in name:
        eprint('You must specify your bot name as "Bot Name@username"')

    name, username = name.rsplit('@', 1)
    name = name.strip()
    username = username.strip()
    if username[-3:].lower() != 'bot':
        username += 'bot'

    message = await await_event(
        client,
        events.NewMessage(FATHER),
        client.send_message(FATHER, '/newbot')
    )
    if message.raw_text.startswith(MAX_BOTS_MESSAGE):
        eprint('You must delete older bots before creating a new one')

    await await_event(
        client,
        events.NewMessage(FATHER),
        client.send_message(FATHER, name)
    )
    message = await await_event(
        client,
        events.NewMessage(FATHER),
        client.send_message(FATHER, username)
    )

    for entity, text in message.get_entities_text():
        if isinstance(entity, types.MessageEntityCode):
            return text

    eprint('Bot created but failed to retrieve token')


async def main():
    config = Config()
    parser = argparse.ArgumentParser()
    parser.add_argument('-a', '--api', help='Sets the apiid:apihash pair')

    parser.add_argument('-r', '--reload', help='Reloads the list of bots',
                        action='store_true')

    parser.add_argument('-l', '--list', help='Lists owned bots',
                        action='store_true')

    parser.add_argument('-c', '--create', help='Creates name@username bot')

    parser.add_argument('-t', '--token', help='Get a existing token for a bot')
    parser.add_argument('-n', '--newtoken', help='Get a new token for a bot')

    args = parser.parse_args()
    if not config.api_id and not args.api:
        eprint('Please configure API ID and hash by running with '
               '--api 12345:1a2b3c4d5e6f')
    elif args.api:
        api_id, api_hash = args.api.split(':')
        config.api_id = int(api_id)
        config.api_hash = api_hash

    async with TelegramClient(
            config.session_name, config.api_id, config.api_hash) as client:
        if args.reload or (args.list and not config.bots):
            config.bots = await load_bots(client)

        if args.list:
            pad = max(len(t[1]) for t in config.bots)
            for bot_id, bot_username in config.bots:
                print('{:<{pad}} ID:{}'
                      .format(bot_username, bot_id, pad=pad))

            print('Total: ', len(config.bots))

        if args.create:
            print(await create_bot(client, args.create))

        if args.token or args.newtoken:
            bot_id = find_bot(config, args.token or args.newtoken)
            print(await get_token(client, bot_id, revoke=bool(args.newtoken)))

if __name__ == '__main__':
    asyncio.get_event_loop().run_until_complete(main())
