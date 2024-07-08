from bs4 import BeautifulSoup
from rapidfuzz import fuzz  # Using rapidfuzz for better performance
from dotenv import load_dotenv
from loguru import logger
import requests
import os
import time
import re
import sys

# Load environment variables from .env file
load_dotenv()

# Define custom log levels
logger.level("ADDED", no=25, color="<green>")
logger.level("DELETED", no=35, color="<red>")

# Loguru configuration
logger.remove()
logger.add(
    sys.stdout, 
    colorize=True, 
    format="<red>{time:MMMM DD YYYY}</red> <white>{time:HH:mm:ss.SS}</white> | {extra[emoji]} <level>{level}</level> | <light-yellow>{extra[function]}</light-yellow> <level>{message}</level>"
)

# Movie-themed emojis for different log levels
LOG_EMOJIS = {
    'DEBUG': '🎬',
    'INFO': '🍿',
    'WARNING': '⚠️',
    'ERROR': '🚨',
    'CRITICAL': '💀',
    'SUCCESS': '✅',
    'ADDED': '➕',
    'DELETED': '❌'
}

def log_with_emoji(level, message, function):
    emoji = LOG_EMOJIS.get(level, '')
    logger.bind(emoji=emoji, function=function).log(level, message)

# Debug tracing flag
trace = False  # Enable detailed logging for troubleshooting

# Headers for HTTP requests
headers = {'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_17) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/104.0.5112.79 Safari/537.36'}

# Trakt API credentials
client_id = os.getenv('CLIENT_ID')
client_secret = os.getenv('CLIENT_SECRET')

# Replace 'your_trakt_username' with your actual Trakt username
trakt_username = os.getenv('TRAKT_USERNAME')

# URLs for Trakt API
auth_base_url = 'https://api.trakt.tv/oauth/device/code'
trakt_token_url = 'https://api.trakt.tv/oauth/device/token'
trakt_base_url = f'https://api.trakt.tv/users/{trakt_username}/'
trakt_list_url_template = f'https://api.trakt.tv/users/{trakt_username}/lists/{{list_name}}/items/'
trakt_list_remove_url_template = f'https://api.trakt.tv/users/{trakt_username}/lists/{{list_name}}/items/remove'
trakt_list_add_url_template = f'https://api.trakt.tv/users/{trakt_username}/lists/{{list_name}}/items'
trakt_search_url = 'https://api.trakt.tv/search/movie,show?query='

# File to store the Trakt token
token_file = 'trakt_token.txt'

# Service names for multiple streaming platforms
services = ['netflix', 'disney', 'hbo', 'apple-tv', 'amazon-prime']  # Removed Hulu and Paramount+

def get_flixpatrol_url(service):
    base_url = "https://flixpatrol.com/top10/"
    urls = {
        'netflix': 'netflix/world/',
        'disney': 'disney/world/',
        'hbo': 'hbo/world/',
        'apple-tv': 'apple-tv/world/',
        'amazon-prime': 'amazon-prime/world/'
    }
    if service in urls:
        return base_url + urls[service]
    else:
        raise ValueError("Unsupported service")

def extract_titles_from_section(section_div):
    titles_list = []
    rows = section_div.find_all('tr', class_='table-group')
    for row in rows:
        td_element = row.find('td', class_='table-td w-1/2')
        if td_element and td_element.find('a'):
            title = td_element.find('a').text.strip()
            titles_list.append(title)
    return titles_list

def get_flixpatrol_top10(service):
    url = get_flixpatrol_url(service)
    res = requests.get(url, headers=headers)
    soup = BeautifulSoup(res.text, 'html.parser')
    
    movies_list = []
    tvshows_list = []

    movies_section = soup.find('div', id=f'{service}-1')
    if movies_section:
        movies_list = extract_titles_from_section(movies_section)

    tvshows_section = soup.find('div', id=f'{service}-2')
    if tvshows_section:
        tvshows_list = extract_titles_from_section(tvshows_section)

    return movies_list, tvshows_list

def find_good_access_token():
    try:
        with open(token_file, 'r') as f:
            file_token = f.read().strip()
            if file_token and get_trakt_me(file_token):
                return file_token
            else:
                open(token_file, 'w').close()
    except FileNotFoundError:
        f = open(token_file, 'a')
        if f:
            f.close()

    auth_code, device_code = get_trakt_code()
    if auth_code:
        log_with_emoji('INFO', 'Please activate Trakt device using:', 'find_good_access_token')
        log_with_emoji('INFO', auth_code, 'find_good_access_token')
        access_token = get_trakt_oauth(device_code)
        if access_token:
            with open(token_file, 'w') as f:
                f.write(access_token)
            return access_token
    log_with_emoji('ERROR', 'Unable to get Trakt authorization', 'find_good_access_token')
    return 'No token'

def get_trakt_code():
    trakt_headers = {'Content-Type': 'application/json', 'trakt-api-key': client_id}
    trakt_payload = {'client_id': client_id}
    response = requests.post(auth_base_url, json=trakt_payload, headers=trakt_headers)
    if response.status_code == 200:
        data = response.json()
        return data['user_code'], data['device_code']
    else:
        if trace:
            log_with_emoji('DEBUG', f"Failed to get device code: {response.status_code}, {response.content.decode()}", 'get_trakt_code')
        return None, None

def get_trakt_oauth(device_code):
    trakt_headers = {'Content-Type': 'application/json', 'trakt-api-key': client_id, 'trakt-api-version': '2'}
    trakt_payload = {'code': device_code, 'client_id': client_id, 'client_secret': client_secret}
    poll_interval = 5
    tries_limit = 40
    tries = 0
    while tries < tries_limit:
        response = requests.post(trakt_token_url, json=trakt_payload, headers=trakt_headers)
        if response.status_code == 200:
            data = response.json()
            return 'Bearer ' + data['access_token']
        elif response.status_code == 400:
            time.sleep(poll_interval)
            tries += 1
        else:
            if trace:
                log_with_emoji('DEBUG', f"Failed to obtain OAuth token: {response.status_code}, {response.content.decode()}", 'get_trakt_oauth')
            break
    return None

def get_trakt_me(test_token):
    trakt_headers = {'content-type': 'application/json', 'authorization': test_token, 'trakt-api-version': '2', 'trakt-api-key': client_id}
    response = requests.get(f'https://api.trakt.tv/users/{trakt_username}', headers=trakt_headers)
    return response.status_code == 200

def make_payload(trakt_id_list):
    payload = {'movies': [], 'shows': []}
    for item in trakt_id_list:
        if item['type'] == 'movie':
            payload['movies'].append({'ids': {'trakt': item['id']}})
        elif item['type'] == 'show':
            payload['shows'].append({'ids': {'trakt': item['id']}})
    return payload

def rate_limited_request(method, url, **kwargs):
    max_retries = 5
    for i in range(max_retries):
        response = method(url, **kwargs)
        if response.status_code == 429:
            retry_after = int(response.headers.get('Retry-After', 1))
            log_with_emoji('WARNING', f'Rate limit exceeded. Retrying after {retry_after} seconds...', 'rate_limited_request')
            time.sleep(retry_after)
        else:
            return response
    log_with_emoji('ERROR', 'Exceeded maximum retries due to rate limiting.', 'rate_limited_request')
    sys.exit()

def process_list(service, combined_list):
    list_name = f'{service.capitalize()}-Top10'
    trakt_headers = {'content-type': 'application/json', 'authorization': token_result, 'trakt-api-version': '2', 'trakt-api-key': client_id}
    list_url = trakt_list_url_template.format(list_name=list_name)

    existing_items = []
    response = requests.get(list_url, headers=trakt_headers)
    if response.status_code == 200:
        existing_items = response.json()
    elif response.status_code == 404:
        Dname = list_name
        Desc = f'Top 10 Movies and TV Shows on {service.capitalize()} in the World, updated daily'
        trakt_payload = {'name': Dname,
                         'description': Desc,
                         'privacy': 'public',
                         'display_numbers': True,
                         'allow_comments': True,
                         'sort_by': 'rank',
                         'sort_how': 'asc'}
        list_url = trakt_base_url + 'lists/'
        response = rate_limited_request(requests.post, list_url, json=trakt_payload, headers=trakt_headers)
        log_with_emoji('INFO', f'List created.', 'process_list')
        if response.status_code != 201:
            log_with_emoji('ERROR', 'Unable to create new Trakt list, bailing out', 'process_list')
            sys.exit()
    else:
        log_with_emoji('ERROR', f"Unexpected response while getting the list: {response.status_code}, {response.content.decode()}", 'process_list')
        return False

    existing_titles = {item['movie']['title'] if 'movie' in item else item['show']['title'] for item in existing_items}
    combined_titles = set(combined_list)

    to_add = combined_titles - existing_titles
    to_delete = existing_titles - combined_titles

    # Add new items that are not in the existing list
    trakt_id_list_to_add = []
    for title in to_add:
        stripped_title = title.strip()
        if trace:
            log_with_emoji('DEBUG', f'Searching for title: {stripped_title}', 'process_list')
        search_url = trakt_search_url + stripped_title + '&fields=title&extended=full'
        response = rate_limited_request(requests.get, search_url, headers=trakt_headers)
        if response.status_code == 200:
            data = response.json()
            if trace:
                log_with_emoji('DEBUG', f'Search results for {stripped_title}', 'process_list')
            for item in data:
                if 'movie' in item:
                    movie_deets = item['movie']
                    similarity_score = fuzz.ratio(stripped_title, movie_deets['title'])
                    if trace:
                        log_with_emoji('DEBUG', f'Comparing "{stripped_title}" with "{movie_deets["title"]}", similarity score: {similarity_score}', 'process_list')
                    if similarity_score > 70:
                        trakt_id_list_to_add.append({'type': 'movie', 'id': movie_deets['ids']['trakt'], 'name': movie_deets['title']})
                        if trace:
                            log_with_emoji('DEBUG', f'Match found for movie: {movie_deets["title"]}', 'process_list')
                        break
                elif 'show' in item:
                    show_deets = item['show']
                    similarity_score = fuzz.ratio(stripped_title, show_deets['title'])
                    if trace:
                        log_with_emoji('DEBUG', f'Comparing "{stripped_title}" with "{show_deets["title"]}", similarity score: {similarity_score}', 'process_list')
                    if similarity_score > 70:
                        trakt_id_list_to_add.append({'type': 'show', 'id': show_deets['ids']['trakt'], 'name': show_deets['title']})
                        if trace:
                            log_with_emoji('DEBUG', f'Match found for show: {show_deets["title"]}', 'process_list')
                        break

    if trakt_id_list_to_add:
        trakt_payload = make_payload(trakt_id_list_to_add)
        add_url = trakt_list_add_url_template.format(list_name=list_name)
        response = rate_limited_request(requests.post, add_url, json=trakt_payload, headers=trakt_headers)
        if response.status_code == 201:
            for item in trakt_id_list_to_add:
                log_with_emoji('ADDED', f"Added {item['type']}: {item['name']}", 'process_list')
            log_with_emoji('ADDED', f"Total items added: {len(trakt_id_list_to_add)}", 'process_list')
        else:
            log_with_emoji('ERROR', f'Error adding items to {service.capitalize()} list on Trakt: {response.status_code}, {response.content.decode()}', 'process_list')

    # Remove items that are no longer in the top 10
    item_del_list = [{'type': item['type'], 'id': item['movie']['ids']['trakt'], 'name': item['movie']['title']} if 'movie' in item else {'type': 'show', 'id': item['show']['ids']['trakt'], 'name': item['show']['title']} for item in existing_items if (item['movie']['title'] if 'movie' in item else item['show']['title']) in to_delete]
    if item_del_list:
        trakt_payload = make_payload(item_del_list)
        remove_url = trakt_list_remove_url_template.format(list_name=list_name)
        response = rate_limited_request(requests.post, remove_url, json=trakt_payload, headers=trakt_headers)
        if response.status_code == 200:
            for item in item_del_list:
                log_with_emoji('DELETED', f"Deleted {item['type']}: {item['name']}", 'process_list')
            log_with_emoji('DELETED', f"Total items deleted: {len(item_del_list)}", 'process_list')
        else:
            log_with_emoji('ERROR', f"Error removing items from the list: {response.status_code}, {response.content.decode()}", 'process_list')

    return True

token_result = find_good_access_token()
if token_result == "No token":
    log_with_emoji('ERROR', 'No valid Trakt token found or created, bailing here', '__main__')
    sys.exit()

for service in services:
    log_with_emoji('INFO', f'Processing top 10 list for {service.capitalize()}', '__main__')
    movies_list, tvshows_list = get_flixpatrol_top10(service)

    combined_list = movies_list + tvshows_list

    if not process_list(service, combined_list):
        log_with_emoji('ERROR', f'Unable to create/update the Trakt list for {service.capitalize()} - bailing here', '__main__')
        sys.exit()
