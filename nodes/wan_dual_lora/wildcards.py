"""
Wildcard processing for WAN Dual LoRA Loader
Supports the same syntax as Mikey's Wildcard Processor
"""

import os
import re
import random
import folder_paths


def get_wildcard_path():
    """Get path to wildcards folder"""
    wildcard_path = os.path.join(folder_paths.get_user_directory(), 'wildcards')
    # Backwards compatibility with pre paths update to comfy
    if not os.path.isdir(wildcard_path):
        wildcard_path = os.path.join(os.path.dirname(folder_paths.__file__), 'wildcards')
    return wildcard_path


def process_choice_syntax(text, seed):
    """
    Process {option1|option2|option3} syntax
    Randomly selects one option from the pipe-separated list
    """
    random.seed(seed)
    pattern = re.compile(r'{([^{}]*)}')

    def replace(m):
        parts = m.group(1).split('|')
        return random.choice(parts)

    # Process recursively to handle nested choices
    while pattern.search(text):
        text = pattern.sub(replace, text)

    return text


def process_random_syntax(text, seed):
    """
    Process <random:min:max> syntax
    Generates a random float between min and max
    """
    random.seed(seed)
    pattern = r'<random:(-?\d*\.?\d+):(-?\d*\.?\d+)>'

    def replace(m):
        min_val = float(m.group(1))
        max_val = float(m.group(2))
        random_value = random.uniform(min_val, max_val)
        return str(round(random_value, 4))

    text = re.sub(pattern, replace, text)
    return text


def process_file_wildcards(text, seed):
    """
    Process __wildcard_name__ syntax
    Reads a random line from wildcards/wildcard_name.txt

    Supports:
    - __name__ - random line from name.txt
    - __path/name__ - random line from path/name.txt
    - 2$$__name__ - 2 random lines from name.txt
    - __name|filter__ - lines containing "filter"
    """
    wildcard_path = get_wildcard_path()

    # Regex pattern for wildcard syntax
    wildcard_regex = r'((\d+)\$\$)?__(!|\+|-|\*)?((?:[^|_]+_)*[^|_]+)((?:\|[^|]+)*)__'

    random.seed(seed)
    offset = seed
    match_strings = []

    new_prompt = ''
    last_end = 0

    for m in re.finditer(wildcard_regex, text):
        full_match, lines_count_str, offset_type, actual_match, words_to_find_str = m.groups()

        # Append everything up to this match
        new_prompt += text[last_end:m.start()]

        # Parse offset modifiers
        lock_indicator = offset_type == '!'
        increment_indicator = offset_type == '+'
        decrement_indicator = offset_type == '-'
        random_indicator = offset_type == '*'

        # Parse filter words
        words_to_find = words_to_find_str.split('|')[1:] if words_to_find_str else None

        # Number of lines to insert
        lines_to_insert = int(lines_count_str) if lines_count_str else 1

        # Handle subdirectories in wildcard path
        match_parts = actual_match.split('/')
        if len(match_parts) > 1:
            wildcard_dir = os.path.join(*match_parts[:-1])
            wildcard_file = match_parts[-1]
        else:
            wildcard_dir = ''
            wildcard_file = match_parts[0]

        search_path = os.path.join(wildcard_path, wildcard_dir)
        file_path = os.path.join(search_path, wildcard_file + '.txt')

        if not os.path.isfile(file_path) and wildcard_dir == '':
            file_path = os.path.join(wildcard_path, wildcard_file + '.txt')

        if os.path.isfile(file_path):
            store_offset = None

            # Handle offset modifiers for repeated wildcards
            if actual_match in match_strings:
                store_offset = offset
                if lock_indicator:
                    offset = seed
                elif random_indicator:
                    offset = random.randint(0, 1000000)
                elif increment_indicator:
                    offset = seed + 1
                elif decrement_indicator:
                    offset = seed - 1
                else:
                    offset = random.randint(0, 1000000)

            selected_lines = []
            with open(file_path, 'r', encoding='utf-8') as file:
                file_lines = file.readlines()
                num_lines = len(file_lines)

                if num_lines > 0:
                    if words_to_find:
                        # Filter by words
                        for i in range(lines_to_insert):
                            start_idx = (offset + i) % num_lines
                            for j in range(num_lines):
                                line_number = (start_idx + j) % num_lines
                                line = file_lines[line_number].strip()
                                if any(re.search(r'\b' + re.escape(word) + r'\b', line, re.IGNORECASE) for word in words_to_find):
                                    selected_lines.append(line)
                                    break
                    else:
                        # Random selection
                        start_idx = offset % num_lines
                        for i in range(lines_to_insert):
                            line_number = (start_idx + i) % num_lines
                            line = file_lines[line_number].strip()
                            selected_lines.append(line)

            # Join selected lines
            if len(selected_lines) == 1:
                replacement_text = selected_lines[0]
            else:
                replacement_text = ', '.join(selected_lines)

            new_prompt += replacement_text
            match_strings.append(actual_match)

            if store_offset is not None:
                offset = store_offset

            offset += lines_to_insert
        else:
            # File not found, keep original text
            new_prompt += m.group(0)

        last_end = m.end()

    new_prompt += text[last_end:]
    return new_prompt


def process_wildcards(text, seed):
    """
    Main wildcard processing pipeline
    Processes all wildcard syntaxes in order:
    1. {choice|syntax}
    2. <random:min:max>
    3. __file_wildcards__

    Runs multiple iterations to handle nested wildcards
    """
    if not text:
        return text

    # Process choice syntax
    text = process_choice_syntax(text, seed)

    # Process random syntax
    text = process_random_syntax(text, seed)

    # Process file wildcards
    new_text = process_file_wildcards(text, seed)

    # Handle nested wildcards (up to 10 iterations)
    if new_text != text:
        for _ in range(10):
            text = new_text
            text = process_choice_syntax(text, seed)
            text = process_random_syntax(text, seed)
            new_text = process_file_wildcards(text, seed)
            if new_text == text:
                break

    return new_text
