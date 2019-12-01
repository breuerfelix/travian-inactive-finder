from datetime import datetime, timedelta
from flask import Flask, request
from flask_cors import CORS
import eventlet
import eventlet.wsgi
import requests
import json
import random
import string
import math


class ApiFailure(Exception):
    """ API did not return expected data """


class Inactives:
    api_entry = 'https://%s.kingdoms.com/api/external.php?'
    actions = {
        'getMapData': 'getMapData',
        'requestApiKey': 'requestApiKey'
    }

    def __init__(self, world, inactivity_days, api_key=None):
        self.world = world
        self.api_entry = Inactives.api_entry % (world,)
        self.api_key = api_key if api_key else self.request_api_key()

        self.map_data = self.get_map_data()
        aged_map_date = (datetime.now() -
                         timedelta(inactivity_days)).strftime("%d.%m.%Y")
        self.aged_map_data = self.get_map_data(date=aged_map_date)

        self.overlapping_players = self.discover_players()
        self.inactive_players = self.discover_inactive_players()

    def request_api_key(self):
        action = Inactives.actions['requestApiKey']
        siteurl = 'https://www.reddit.com'
        sitename = ''.join(random.choices(string.ascii_uppercase, k=8))
        email = f'{sitename}@gmail.com'
        public = 'false'

        url = self._format_url(action=action, siteurl=siteurl,
                               sitename=sitename, email=email, public=public)
        response = requests.get(url)
        response = response.json()
        try:
            return response['response']['privateApiKey']
        except KeyError:
            raise ApiFailure('API did not return a privateApiKey')

    def _format_url(self, action=None, email=None, sitename=None, siteurl=None,
                    public=None, privateapikey=None, date=None):
        url = self.api_entry
        if action:
            url += f'action={action}&'
        if email:
            url += f'email={email}&'
        if sitename:
            url += f'siteName={sitename}&'
        if siteurl:
            url += f'siteUrl={siteurl}&'
        if public:
            url += f'public={public}&'
        if privateapikey:
            url += f'privateApiKey={privateapikey}&'
        if date:
            url += f'date={date}&'

        # Take off the last separator
        url = url[:-1]
        return url

    def get_map_data(self, date=None):
        action = Inactives.actions['getMapData']
        privateapikey = self.api_key

        url = self._format_url(action=action, privateapikey=privateapikey,
                               date=date)
        response = requests.get(url)
        response = response.json()
        try:
            response = response['response']
            return response
        except KeyError:
            raise ApiFailure('API did not return MapData')

    def discover_players(self):
        # Filter out new players
        recent_players = self.map_data['players']
        aged_players = self.aged_map_data['players']
        overlap_recent_players = []
        overlap_aged_players = []
        for recent_player in recent_players:
            for aged_player in aged_players:
                if recent_player['playerId'] == aged_player['playerId']:
                    overlap_recent_players.append(recent_player)
                    overlap_aged_players.append(aged_player)
        return list(zip(overlap_recent_players, overlap_aged_players))

    def discover_inactive_players(self):
        inactive_players = []
        for player in self.overlapping_players:
            recent_data = player[0]
            aged_data = player[1]

            if len(recent_data['villages']) != len(aged_data['villages']):
                # Can't be inactive due to increase in village quantity
                pass
            else:
                if self._compare_village_populations(recent_data['villages'],
                                                     aged_data['villages']):
                    # Population difference detected
                    pass
                else:
                    inactive_players.append(recent_data)
        return inactive_players

    def _compare_village_populations(self, recent_data, aged_data):
        for recent_village in recent_data:
            found = False
            for aged_village in aged_data:
                if int(aged_village['villageId']) == int(recent_village['villageId']):
                    recent = int(recent_village['population'])
                    aged = int(aged_village['population'])
                    if recent > aged:
                        return True

                    # village got cat down more than residence and wall, player might still be active
                    if recent < (aged - 30):
                        return True

                    found = True
                    # go on with the next recent village
                    break

            if not found:
                # village got not found, player moved via menhir
                return True

        return False

    def get_inactives_by_pop(self, max_pop):
        matches = []
        for player in self.inactive_players:
            player_pop = 0
            for village in player['villages']:
                player_pop += int(village['population'])
            if player_pop <= max_pop:
                matches.append(player)
        return matches

    def get_inactives(self, min_village_pop, max_village_pop, min_player_pop, max_player_pop, x, y, min_distance, max_distance):
        matches = []
        for player in self.inactive_players:
            player_pop = 0
            for village in player['villages']:
                player_pop += int(village['population'])

            if player_pop > max_player_pop or player_pop < min_player_pop:
                # continue if max player pop is reached or min is reached
                continue

            # max player pop didnt reached
            for village in player['villages']:
                vil_pop = int(village['population'])
                if vil_pop > max_village_pop or vil_pop < min_village_pop:
                    # continue if pop is too high or too low
                    continue

                distance = self.calculate_distance(village, x, y)

                if distance > max_distance or distance < min_distance:
                    # continue of distance is too high or too low
                    continue

                converted_obj = self.clash_village_player(
                    village, player, distance)
                matches.append(converted_obj)

        # sort by distance, lowest on top
        matches.sort(key=lambda x: float(x['distance']))
        return matches

    def calculate_distance(self, village, x, y):
        return math.hypot(int(village['x']) - x, int(village['y']) - y)

    def clash_village_player(self, village, player, distance):
        return {
            'villageId': village['villageId'],
            'x': village['x'],
            'y': village['y'],
            'population': village['population'],
            'village_name': village['name'],
            'isMainVillage': village['isMainVillage'],
            'isCity': village['isCity'],
            'playerId': player['playerId'],
            'player_name': player['name'],
            'tribeId': player['tribeId'],
            'kingdomId': player['kingdomId'],
            'distance': distance
        }


app = Flask(__name__)
CORS(app)
PORT = 80


@app.route("/")
def get_inactives():
    try:
        gameworld = request.args.get('gameworld')
        inactive_for = request.args.get('inactive_for')
        min_village_pop = request.args.get('min_village_pop')
        max_village_pop = request.args.get('max_village_pop')
        min_player_pop = request.args.get('min_player_pop')
        max_player_pop = request.args.get('max_player_pop')
        x = request.args.get('x')
        y = request.args.get('y')
        min_distance = request.args.get('min_distance')
        max_distance = request.args.get('max_distance')

        if not gameworld:
            return json.dumps({
                'error': True,
                'message': "no gameworld provided",
                'data': []
            })

        # default values
        if not inactive_for:
            inactive_for = 5
        if not min_village_pop:
            min_village_pop = 0
        if not max_village_pop:
            max_village_pop = 200
        if not x:
            x = 0
        if not y:
            y = 0
        if not min_distance:
            min_distance = 0
        if not max_distance:
            max_distance = 100
        if not min_player_pop:
            min_player_pop = 0
        if not max_player_pop:
            max_player_pop = 500

        # type conversion
        inactive_for = int(inactive_for)
        min_village_pop = int(min_village_pop)
        max_village_pop = int(max_village_pop)
        x = int(x)
        y = int(y)
        min_distance = float(min_distance)
        max_distance = float(max_distance)
        min_player_pop = int(min_player_pop)
        max_player_pop = int(max_player_pop)

        inactives = Inactives(gameworld, inactive_for)
        inactive_players = inactives.get_inactives(
            min_village_pop, max_village_pop, min_player_pop, max_player_pop,
            x, y, min_distance, max_distance)
        return json.dumps({
            'error': False,
            'message': '',
            'data': inactive_players
        })
    except Exception as e:
        return json.dumps({
            'error': True,
            'message': str(e),
            'data': []
        })


# run server
if __name__ == '__main__':
    eventlet.wsgi.server(eventlet.listen(('', PORT)), app)
    # app.run(debug=True, port=PORT) # for flask debug
