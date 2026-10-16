| survey |
| | type | name | label | relevant | required | constraint | constraint_message | appearance | calculation | parameters |
| | hidden | cond | | | | | | | | |
| | hidden | seed | | | | | | | | |
| | hidden | order_att | | | | | | | | |
| | hidden | order_blocks | | | | | | | | |
| | begin group | p_consent | Consent | | | | | field-list | | |
| | select_one yesno | consent | Do you agree to take part in this (fake) study? | | yes | | | | | |
| | end group | | | | | | | | | |
| | begin group | p_age | About you | ${consent} = 'yes' | | | | field-list | | |
| | integer | age | How old are you? | | yes | . >= 18 and . <= 120 | Age must be 18 to 120 | | | |
| | end group | | | | | | | | | |
| | begin group | p_stim_a | Stimulus | ${consent} = 'yes' and ${cond} = 'A' | | | | field-list | | |
| | note | stim_a | STIMULUS-A: a short story about a red kite. | | | | | | | |
| | end group | | | | | | | | | |
| | begin group | p_stim_b | Stimulus | ${consent} = 'yes' and ${cond} = 'B' | | | | field-list | | |
| | note | stim_b | STIMULUS-B: a short story about a blue whale. | | | | | | | |
| | end group | | | | | | | | | |
| | begin group | p_att | Attitudes | ${consent} = 'yes' | | | | field-list | | |
| | select_one likert | att1 | ATT1: After the condition ${cond} story, how much did you enjoy it? | | yes | | | | | |
| | select_one likert | att2 | ATT2: How interesting was it? | | yes | | | | | |
| | select_one likert | att3 | ATT3: How believable was it? | | yes | | | | | |
| | end group | | | | | | | | | |
| | calculate | att1_label | | | | | | | jr:choice-name(${att1}, '${att1}') | |
| | begin group | p_follow | Follow-up | ${consent} = 'yes' and ${att1} >= 4 | | | | field-list | | |
| | text | followup | FOLLOWUP: You chose ${att1} (${att1_label}). What did you enjoy? | | yes | | | | | |
| | end group | | | | | | | | | |
| | begin group | p_colour | Colours | ${consent} = 'yes' | | | | field-list | | |
| | select_one colour | fav_colour | COLOUR: Pick a colour (choice order randomised with the session seed) | | | | | | | randomize=true seed=${seed} |
| | end group | | | | | | | | | |
| | begin group | blk_x | Block X | ${consent} = 'yes' | | | | field-list | | |
| | integer | q_x | BLOCKX: Any number (optional) | | | | | | | |
| | end group | | | | | | | | | |
| | begin group | blk_y | Block Y | ${consent} = 'yes' | | | | field-list | | |
| | integer | q_y | BLOCKY: Any number (optional) | | | | | | | |
| | end group | | | | | | | | | |

| choices |
| | list_name | name | label |
| | yesno | yes | Yes |
| | yesno | no | No |
| | likert | 1 | Strongly disagree |
| | likert | 2 | Disagree |
| | likert | 3 | Neutral |
| | likert | 4 | Agree |
| | likert | 5 | Strongly agree |
| | colour | red | Red |
| | colour | green | Green |
| | colour | blue | Blue |
| | colour | yellow | Yellow |
| | colour | purple | Purple |

| settings |
| | form_title | form_id | version | style |
| | Enketo spike survey | spike_enketo | 2026101601 | pages |
