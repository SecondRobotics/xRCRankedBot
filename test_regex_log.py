import re

# Define the regex pattern for lines like '6/3/2025 2:06:07 AM: whatdidido: gg.'
pattern = re.compile(r'^\d{1,2}/\d{1,2}/\d{4} \d{1,2}:\d{2}:\d{2} [AP]M: (\w+): (.+)\.$')

input_file = '11115.log'
output_file = 'chat_messages.log'

with open(input_file, 'r', encoding='utf-8') as infile, open(output_file, 'w', encoding='utf-8') as outfile:
    for line in infile:
        if pattern.match(line) and 'KeyNotFoundException' not in line:
            print(line.strip())
            outfile.write(line) 