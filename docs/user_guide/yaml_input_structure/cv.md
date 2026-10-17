# `cv` Field

## Header Information

The `cv` field begins with your personal information. All fields are optional. RenderCV adapts to whatever you provide.

```yaml
cv:
  name: John Doe
  headline: Machine Learning Engineer
  location: San Francisco, CA
  email: john@example.com # (1)!
  phone: "+14155551234" # (2)!
  website: https://johndoe.dev # (3)!
  photo: photo.jpg
  social_networks:
    - network: LinkedIn # (4)!
      username: johndoe
    - network: GitHub
      username: johndoe
  custom_connections:
    - placeholder: Book a call # (5)!
      url: https://cal.com/johndoe
      fontawesome_icon: calendar-days
```

1. Multiple emails can be provided as a list.
2. Multiple phone numbers can be provided as a list. The display format (national, international, or E164) can be controlled with [`design.header.connections.phone_number_format`](design.md).
3. Multiple websites can be provided as a list.
4. Available social networks: << available_social_networks >>
5. Custom connections let you add any extra link (or plain text if `url` is omitted) with your own display text (`placeholder`) and a Font Awesome icon name (e.g., `calendar-days`, `envelope`). For the list of available icons, see [fontawesome.com/search](https://fontawesome.com/search).

## Sections

The `sections` field holds the main content of your CV. It's a dictionary where:

- **Keys** are section titles (displayed as headings). Section titles can be anything.
- **Values** are lists of entries, or objects with `entries` and an optional `hidden` flag.

```yaml
cv:
  name: John Doe

  sections:
    summary:
      - Software engineer with 10 years of experience in distributed systems.

    experience:
      - company: Acme Corp
        position: Senior Engineer
        start_date: 2020-01
        end_date: present
        highlights:
          - Led migration to microservices architecture
          - Reduced deployment time by 80%

    education:
      - institution: MIT
        area: Computer Science
        degree: BS
        start_date: 2012-09
        end_date: 2016-05

    skills:
      - label: Languages
        details: Python, Go, Rust, TypeScript
      - label: Infrastructure
        details: Kubernetes, Terraform, AWS
```


**Section names are just titles.** You can use any of the << entry_count >> entry types in any section. Choose what works best for your content.

For example, `experience` section could use `NormalEntry`:

```yaml
sections:
  experience:
    - name: Acme Corp — Senior Engineer
      start_date: 2020-01
      end_date: present
      highlights:
        - Led migration to microservices architecture
```

Or `BulletEntry` for a minimal style:

```yaml
sections:
  experience:
    - bullet: "**Acme Corp** — Senior Engineer (2020–present)"
    - bullet: "**StartupXYZ** — Founding Engineer (2018–2020)"
```


!!! warning "One entry type per section"
    Each section must contain only one type of entry. For example, you cannot mix `ExperienceEntry` and `EducationEntry` in the same section.

## Hiding sections and entries

Set `hidden: true` to omit a whole section or one entry from Typst, PDF, PNG,
Markdown, and HTML output. Omitted `hidden` flags default to `false`.
The input YAML and serialized model retain hidden content. Hidden entries still
undergo validation, including required fields, dates, and the one-entry-type-per-section rule.

To hide one structured entry, add the flag without changing its surrounding list:

```yaml
cv:
  sections:
    education:
      - institution: A University
        area: Computer Science
        hidden: true
```

To hide a whole section, change that section's value from a list to an object and
move the **entire list** under `entries`:

```yaml
cv:
  sections:
    education:
      hidden: true
      entries:
        - institution: A University
          area: Computer Science
        - institution: B University
          area: Mathematics
          hidden: true
```

Setting the section's `hidden` to `false` shows A University again; B University
remains hidden. A section whose entries are all hidden does not produce an empty
heading. Deliberately empty legacy sections (`education: []`) keep their previous behavior.

A plain text entry needs an object to carry the flag. Both forms may appear in
the same text section:

```yaml
cv:
  sections:
    summary:
      - This existing plain text entry remains visible.
      - text: This text is saved but not rendered.
        hidden: true
      - text: This text is visible again.
        hidden: false
```

Existing YAML does not need conversion. Unhiding requires only changing the flag;
the `entries` or `text` wrapper can remain. Serialization may omit `hidden: false`
because it is the default, but always retains `hidden: true` and hidden content.
`hidden` is reserved visibility metadata, not a custom template placeholder.

These formats are extensions of this RenderCV build. A browser editor and a local
CLI must use the same modified RenderCV package and its generated `schema.json`.
An unmodified upstream installation does not implement this feature. Newly
generated YAML points to this fork's schema for language-server completion.
For existing YAML, replace the upstream schema comment with:

```yaml
# yaml-language-server: $schema=https://raw.githubusercontent.com/sshawn9/rendercv/main/schema.json
```

While working with unpublished changes, point the editor at the local `schema.json`.
The remote schema reflects the changes after they are published to this fork.

## Entry Types

RenderCV provides << entry_count >> entry types:
{$ for entry_name in entry_names $}
<< loop.index >>. << entry_name >>
{$ endfor $}
each rendered differently on the PDF.

{$ for entry_name, entry in sample_entries.items() $}
### << entry_name >>

{$ if entry_name == "EducationEntry" $}
For academic credentials.

| Field         | Required | Description                              |
| ------------- | -------- | ---------------------------------------- |
| `institution` | Yes      | School or university name                |
| `area`        | Yes      | Field of study                           |
| `degree`      | No       | Degree type (BS, MS, PhD, etc.)          |
| `date`        | No       | Custom date string (overrides start/end) |
| `start_date`  | No       | Start date                               |
| `end_date`    | No       | End date (or `present`)                  |
| `location`    | No       | Institution location                     |
| `summary`     | No       | Brief description                        |
| `highlights`  | No       | List of bullet points                    |

{$ elif entry_name == "ExperienceEntry" $}
For work history and professional roles.

| Field        | Required | Description                              |
| ------------ | -------- | ---------------------------------------- |
| `company`    | Yes      | Employer name                            |
| `position`   | Yes      | Job title                                |
| `date`       | No       | Custom date string (overrides start/end) |
| `start_date` | No       | Start date                               |
| `end_date`   | No       | End date (or `present`)                  |
| `location`   | No       | Office location                          |
| `summary`    | No       | Role description                         |
| `highlights` | No       | List of accomplishments                  |

{$ elif entry_name == "PublicationEntry" $}
For papers, articles, and other publications.

| Field     | Required | Description                                      |
| --------- | -------- | ------------------------------------------------ |
| `title`   | Yes      | Publication title                                |
| `authors` | Yes      | List of author names (use `*Name*` for emphasis) |
| `doi`     | No       | Digital Object Identifier                        |
| `url`     | No       | Link to the publication                          |
| `journal` | No       | Journal, conference, or venue name               |
| `date`    | No       | Publication date                                 |

{$ elif entry_name == "NormalEntry" $}
A flexible entry for projects, awards, certifications, or anything else.

| Field        | Required | Description                              |
| ------------ | -------- | ---------------------------------------- |
| `name`       | Yes      | Entry title                              |
| `date`       | No       | Custom date string (overrides start/end) |
| `start_date` | No       | Start date                               |
| `end_date`   | No       | End date (or `present`)                  |
| `location`   | No       | Associated location                      |
| `summary`    | No       | Brief description                        |
| `highlights` | No       | List of bullet points                    |

{$ elif entry_name == "OneLineEntry" $}
For compact key-value pairs, ideal for skills or technical proficiencies.

| Field     | Required | Description        |
| --------- | -------- | ------------------ |
| `label`   | Yes      | Category name      |
| `details` | Yes      | Associated details |

{$ elif entry_name == "BulletEntry" $}
A single bullet point. Use for simple lists.

| Field    | Required | Description     |
| -------- | -------- | --------------- |
| `bullet` | Yes      | The bullet text |

{$ elif entry_name == "NumberedEntry" $}
An automatically numbered entry.

| Field    | Required | Description       |
| -------- | -------- | ----------------- |
| `number` | Yes      | The entry content |

{$ elif entry_name == "ReversedNumberedEntry" $}
A numbered entry that counts down (useful for publication lists where recent items come first).

| Field             | Required | Description       |
| ----------------- | -------- | ----------------- |
| `reversed_number` | Yes      | The entry content |

{$ elif entry_name == "TextEntry" $}
Plain text without structure. Just write a string.

{$ endif $}

```yaml
<< entry["yaml"] >>
```

{$ for figure in entry["figures"] $}
=== "`<< figure["theme"] >>` theme"
    ![<< figure["alt_text"] >>](<< figure["path"] >>)
{$ endfor $}

{$ endfor $}

## Text Formatting & Features

### Using Markdown

All text fields support basic Markdown:

```yaml
highlights:
  - Increased revenue by **$2M** annually
  - Developed [open-source tool](https://github.com/example) with *500+ stars*
```

- `**text**` → **bold**
- `*text*` → *italic*
- `[text](url)` → hyperlink
- `` `code` `` → `code`

### Using Typst

All text fields support

- Typst math (surround with `$$` like `$$f(x) = x^2$$`)
- Typst commands (like `#emph[emphasized]`).

```yaml
highlights:
  - Showed that $$f(x) = x^2$$ is a parabola
  - "This is an #emph[emphasized] text"
```

### Arbitrary Keys

You can add arbitrary keys to any entry. By default, they're ignored, but you can reference them in `design.templates` field. See [Arbitrary Keys in Entries](../how_to/arbitrary_keys_in_entries.md) for more information.

```yaml hl_lines="6"
experience:
  - company: Startup Inc
    position: Founder
    start_date: 2020-01
    end_date: present
    revenue: $5M ARR  # Custom field
    highlights:
      - Built product from zero to profitability
```


## Hiding personal information

Use `cv.hidden_fields` to omit personal information from Typst, PDF, PNG,
Markdown, and HTML output while keeping its original values in your YAML:

```yaml
cv:
  name: Example Candidate
  email:
    - first@example.com
    - second@example.com
  photo: images/photo.png
  hidden_fields:
    - photo
    - email
```

The allowed names are `name`, `headline`, `location`, `photo`, `email`, `phone`,
`website`, `social_networks`, and `custom_connections`. The default is `[]`;
omitting the field also shows everything. Unknown names, non-list values, and
non-string list items are validation errors. Lists are hidden as a whole:
`email` hides every email address, and `social_networks` hides every account.
Fields retain their existing scalar/list types; no `{value, hidden}` wrapper is
introduced. Remove a name from `hidden_fields` to show that field again.

Rendering uses an independent copy. The YAML, source model, personal values,
field order, and section/entry visibility are preserved. Ordinary hidden fields
still undergo normal content validation, such as email and phone validation.
An empty `hidden_fields` may be omitted during serialization; nonempty lists and
hidden values are retained.

A hidden photo keeps its path or HTTP(S) URL and still receives type/basic format
validation. It is never checked for existence, read, downloaded, decoded, copied,
or embedded. Missing files and unreachable URLs therefore do not prevent
rendering while `photo` is hidden. The existing layout without a photo is used.
Showing the photo again restores normal resource validation and rendering.
Watch mode re-reads visibility when the CV YAML changes; hidden photo resources
do not enter input-file discovery.

Hiding `name` also removes its automatic header, footer, top-note, and PDF author
and title contributions. Only standalone `NAME` placeholders and their directly
adjacent separators are removed from the rendering copy. Other identifiers such
as `MONTH_NAME` and custom text (including words like `by`) are preserved.
Markdown formatting around remaining content stays intact: `**NAME's CV**`
becomes `**CV**`, and `***NAME** CV*` becomes `*CV*`. Links whose labels become
empty are removed with their destinations; links with remaining label text retain
their URL and title. A footer or top note containing only the hidden name is
disabled.
Literal text elsewhere in the CV or in a custom template is not redacted.
**Output filenames still follow the original naming rules and may contain the
name.**

For applications editing this YAML, save the complete original values and a
`hidden_fields` array of the names above. To hide a field, add its name; to show it,
remove its name. Do not delete the value. Render and export through a RenderCV
version that supports this field so browser and local rendering use the same
visibility protocol. Re-render from the complete source whenever visibility changes;
do not reuse Markdown, HTML, or Typst output generated with different visibility.
