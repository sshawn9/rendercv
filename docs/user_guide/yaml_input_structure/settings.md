# `settings` Field

The `settings` field configures RenderCV's behavior, including output paths, file generation, and text formatting.

```yaml
settings:
  current_date: '2025-12-03' # (5)!
  render_command:
    design: path/to/design.yaml # (1)!
    locale: path/to/locale.yaml # (2)!
    typst_path: rendercv_output/NAME_IN_SNAKE_CASE_CV.typ # (3)!
    pdf_path: rendercv_output/NAME_IN_SNAKE_CASE_CV.pdf
    markdown_path: rendercv_output/NAME_IN_SNAKE_CASE_CV.md
    html_path: rendercv_output/NAME_IN_SNAKE_CASE_CV.html
    png_path: rendercv_output/NAME_IN_SNAKE_CASE_CV.png
    dont_generate_markdown: false
    dont_generate_html: false
    dont_generate_typst: false
    dont_generate_pdf: false
    dont_generate_png: false
  bold_keywords: # (4)!
    - AWS
    - Python
```


1. You can optionally split your YAML into multiple files. This file contains the `design` field.
2. You can optionally split your YAML into multiple files. This file contains the `locale` field.
3. Available placeholders are: `NAME`, `NAME_IN_SNAKE_CASE`, `NAME_IN_LOWER_SNAKE_CASE`, `NAME_IN_UPPER_SNAKE_CASE`, `NAME_IN_KEBAB_CASE`, `NAME_IN_LOWER_KEBAB_CASE`, `NAME_IN_UPPER_KEBAB_CASE`, `MONTH_NAME`, `MONTH_ABBREVIATION`, `MONTH`, `MONTH_IN_TWO_DIGITS`, `YEAR`, `YEAR_IN_TWO_DIGITS`.
4. These keywords will be bolded wherever they appear in your CV text (highlights, summaries, etc.).
5. Date used for file naming (when using date placeholders), the "last updated" text in the top note, and time span calculations for ongoing events (entries with `end_date: present`)


## Using a separate settings file

A separate settings file must contain the `settings` field, just like the main CV file:

```yaml
# settings.yaml
settings:
  render_command:
    design: design.yaml
    locale: locale.yaml
```

```bash
rendercv render cv.yaml --settings settings.yaml
```

This loads the referenced design and locale files as well. The separate `settings` field replaces the main file's `settings` field in full. Relative paths inside YAML are resolved from the **main CV file's directory**, including references in a separate settings file. File paths passed directly with `--settings`, `--design`, and `--locale-catalog` are resolved from the current working directory.

`--design` and `--locale-catalog` take precedence over YAML references. Dotted field overrides, such as `--settings.render_command.design other.yaml` or `--design.theme classic`, are applied last. A dotted file reference follows the same path rules as its YAML field.

With `--watch`, edits to the main CV, settings, design, or locale files reload their current contents. Changing a design or locale reference also updates the files being watched. Atomic replacement saves and files created after an error are detected too.
