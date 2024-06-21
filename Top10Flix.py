import requests
import os
import time
from bs4 import BeautifulSoup
import sys
from rapidfuzz import fuzz  # Using rapidfuzz for better performance
import re
from dotenv import load_dotenv

# Debug tracing flag
trace = False  # Enable detailed logging for troubleshooting

# Load environment variables from .env file
load_dotenv()

# Access the environment variables
client_id = os.getenv('CLIENT_ID')
client_secret = os.getenv('CLIENT_SECRET')
trakt_username = os.getenv('TRAKT_USERNAME')

# Headers for HTTP requests
headers = {'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_17) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/104.0.5112.79 Safari/537.36'}

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
services = ['netflix', 'disney', 'hbo', 'apple-tv', 'amazon-prime']

# Function to get the FlixPatrol URL for a given service
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

# Function to extract titles from a specific section (Movies or TV Shows)
def extract_titles_from_section(section_div):
    """
    Extracts and cleans the titles from a given section div (Movies or TV Shows).
    """
    titles_list = []

    rows = section_div.find_all('tr', class_='table-group')
    for row in rows:
        # Extract title from <a> tag within the appropriate <td>
        td_element = row.find('td', class_='table-td w-1/2')
        if td_element and td_element.find('a'):
            title = td_element.find('a').text.strip()
            # Do not append the year to the title
            titles_list.append(title)
    
    return titles_list

# Function to fetch and parse the top 10 list from FlixPatrol
def get_flixpatrol_top10(service):
    url = get_flixpatrol_url(service)
    res = requests.get(url, headers=headers)
    soup = BeautifulSoup(res.text, 'html.parser')
    
    movies_list = []
    tvshows_list = []

    # Find the Movies section
    movies_section = soup.find('div', id=f'{service}-1')
    if movies_section:
        movies_list = extract_titles_from_section(movies_section)

    # Find the TV Shows section
    tvshows_section = soup.find('div', id=f'{service}-2')
    if tvshows_section:
        tvshows_list = extract_titles_from_section(tvshows_section)

    return movies_list, tvshows_list
    
for service in services:
    print(f"Top 10 for {service.capitalize()}:")
    movies, tvshows = get_flixpatrol_top10(service)
    
    print("\nMovies:")
    for title in movies:
        print(title)
    
    print("\nTV Shows:")
    for title in tvshows:
        print(title)
    print("\n" + "-"*40 + "\n")

# Function to get a valid Trakt access token
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
        print('Please activate Trakt device using:', auth_code)
        access_token = get_trakt_oauth(device_code)
        if access_token:
            with open(token_file, 'w') as f:
                f.write(access_token)
            return access_token
    print('Unable to get Trakt authorization')
    return 'No token'

# Function to get the Trakt authorization code
def get_trakt_code():
    trakt_headers = {'Content-Type': 'application/json', 'trakt-api-key': client_id}
    trakt_payload = {'client_id': client_id}
    response = requests.post(auth_base_url, json=trakt_payload, headers=trakt_headers)
    if response.status_code == 200:
        data = response.json()
        return data['user_code'], data['device_code']
    else:
        if trace:
            print(f"Failed to get device code: {response.status_code}, {response.content.decode()}")
        return None, None

# Function to get the Trakt OAuth token
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
                print(f"Failed to obtain OAuth token: {response.status_code}, {response.content.decode()}")
            break
    return None

# Function to validate the Trakt token
def get_trakt_me(test_token):
    trakt_headers = {'content-type': 'application/json', 'authorization': test_token, 'trakt-api-version': '2', 'trakt-api-key': client_id}
    response = requests.get(f'https://api.trakt.tv/users/{trakt_username}', headers=trakt_headers)
    return response.status_code == 200

# Function to create a payload for Trakt list update
def make_payload(trakt_id_list):
    payload = {'movies': [], 'shows': []}
    for item in trakt_id_list:
        if item['type'] == 'movie':
            payload['movies'].append({'ids': {'trakt': item['id']}})
        elif item['type'] == 'show':
            payload['shows'].append({'ids': {'trakt': item['id']}})
    return payload

# Function to handle rate-limited requests with retries
def rate_limited_request(method, url, **kwargs):
    max_retries = 5
    for i in range(max_retries):
        response = method(url, **kwargs)
        if response.status_code == 429:
            retry_after = int(response.headers.get('Retry-After', 1))
            print(f'Rate limit exceeded. Retrying after {retry_after} seconds...')
            time.sleep(retry_after)
        else:
            return response
    print('Exceeded maximum retries due to rate limiting.')
    sys.exit()

# Function to process the Trakt list (create, update, clear)
def process_list(service, combined_list):
    list_name = f'{service.capitalize()}-Top10'
    trakt_headers = {'content-type': 'application/json', 'authorization': token_result, 'trakt-api-version': '2', 'trakt-api-key': client_id}
    list_url = trakt_list_url_template.format(list_name=list_name)

    # Initialize data as an empty list
    data = []

    # Attempt to retrieve the existing list
    response = requests.get(list_url, headers=trakt_headers)
    if response.status_code == 200:
        data = response.json()
    elif response.status_code == 404:
        # List doesn't exist, create it
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
        if trace:
            print(f'List created. Trakt response code: {response.status_code}')
            print(f'Trakt response content for list creation: {response.content.decode()}')
        if response.status_code != 201:
            print('Unable to create new Trakt list, bailing out')
            sys.exit()
    else:
        print(f"Unexpected response while getting the list: {response.status_code}, {response.content.decode()}")
        return False

    # If we have existing data, prepare to remove current items
    if data:
        item_del_list = [{'type': item['type'], 'id': item['movie']['ids']['trakt']} if 'movie' in item else {'type': 'show', 'id': item['show']['ids']['trakt']} for item in data]
        trakt_payload = make_payload(item_del_list)
        remove_url = trakt_list_remove_url_template.format(list_name=list_name)
        response = rate_limited_request(requests.post, remove_url, json=trakt_payload, headers=trakt_headers)
        if trace:
            print(f'Items removed. Trakt response code for item removal: {response.status_code}')
            print(f'Trakt response content for item removal: {response.content.decode()}')
        if response.status_code != 204:
            print(f"Error removing items from the list: {response.status_code}, {response.content.decode()}")

    return True

# Main script execution
token_result = find_good_access_token()
if token_result == "No token":
    print('No valid Trakt token found or created, bailing here')
    sys.exit()

for service in services:
    print(f'Processing top 10 list for {service.capitalize()}')
    movies_list, tvshows_list = get_flixpatrol_top10(service)

    combined_list = movies_list + tvshows_list  # Combine movies and TV shows into one list

    if not process_list(service, combined_list):
        print(f'Unable to create/update the Trakt list for {service.capitalize()} - bailing here')
        sys.exit()

    trakt_headers = {'content-type': 'application/json', 'authorization': token_result, 'trakt-api-version': '2', 'trakt-api-key': client_id}
    trakt_id_list = []
    for title in combined_list:
        stripped_title = title.strip()
        if trace:
            print(f'Searching for title: {stripped_title}')  # Log the title being searched
        search_url = trakt_search_url + stripped_title + '&fields=title&extended=full'
        response = rate_limited_request(requests.get, search_url, headers=trakt_headers)
        if response.status_code == 200:
            data = response.json()
            if trace:
                print(f'Search results for {stripped_title}: {data}')  # Log the search results
            for item in data:
                if 'movie' in item:
                    movie_deets = item['movie']
                    similarity_score = fuzz.ratio(stripped_title, movie_deets['title'])
                    if trace:
                        print(f'Comparing "{stripped_title}" with "{movie_deets["title"]}", similarity score: {similarity_score}')  # Log the comparison
                    if similarity_score > 70:  # Lowered threshold to capture more matches
                        trakt_id_list.append({'type': 'movie', 'id': movie_deets['ids']['trakt']})
                        if trace:
                            print(f'Match found for movie: {movie_deets["title"]}')  # Log the matched movie
                        break
                elif 'show' in item:
                    show_deets = item['show']
                    similarity_score = fuzz.ratio(stripped_title, show_deets['title'])
                    if trace:
                        print(f'Comparing "{stripped_title}" with "{show_deets["title"]}", similarity score: {similarity_score}')  # Log the comparison
                    if similarity_score > 70:  # Lowered threshold to capture more matches
                        trakt_id_list.append({'type': 'show', 'id': show_deets['ids']['trakt']})
                        if trace:
                            print(f'Match found for show: {show_deets["title"]}')  # Log the matched show
                        break

    if not trakt_id_list:
        print(f'No matches found for titles from {service.capitalize()}')  # Log if no matches found

    trakt_payload = make_payload(trakt_id_list)
    add_url = trakt_list_add_url_template.format(list_name=f'{service.capitalize()}-Top10')
    response = rate_limited_request(requests.post, add_url, json=trakt_payload, headers=trakt_headers)
    if trace:
        print(f'Items added. Trakt response code for adding items: {response.status_code}')
        print(f'Trakt response content for adding items: {response.content.decode()}')
    if response.status_code != 201:
        print(f'Error adding items to {service.capitalize()} list on Trakt: {response.status_code}, {response.content.decode()}')
