import time
import asyncio
from datetime import datetime
import re
from pathlib import Path
from collections import OrderedDict

from addict import Dict
import pyppeteer
import typer
import best_of.generator
import best_of.md_generation
import best_of.utils


def chunker(seq, size):
    """Iterates over a sequence in chunks."""
    # From https://stackoverflow.com/questions/434287/what-is-the-most-pythonic-way-to-iterate-over-a-list-in-chunks
    return (seq[pos : pos + size] for pos in range(0, len(seq), size))


def shorten(s, max_len):
    """Shorten a string by appending ... if it's too long."""
    if len(s) > max_len:
        s = s[: max_len - 3] + "..."
    return s


async def save_screenshot(
    url: str, img_path: str, sleep: int = 5, width: int = 1024, height: int = 576
):
    """Loads url in headless browser and saves screenshot to file (.jpg or .png)."""
    browser = await pyppeteer.launch()
    page = await browser.newPage()
    await page.goto(url, {"timeout": 6000})  # increase timeout to 60 s for heroku apps
    await page.emulate({"viewport": {"width": width, "height": height}})
    time.sleep(sleep)
    # Type (PNG or JPEG) will be inferred from file ending.
    await page.screenshot({"path": img_path})
    await browser.close()


def generate_project_html(project: Dict, configuration: Dict, labels: Dict = None):
    """Generates the content of the table cell for a project."""

    project_md = ""

    if project.image:
        img_path = project.image
    else:
        # Make screenshot of the homepage.
        screenshot_dir = Path("screenshots")
        screenshot_dir.mkdir(parents=True, exist_ok=True)
        img_filename = "".join([c for c in project.name if c.isalpha()]) + ".png"
        img_path = screenshot_dir / img_filename

        if configuration.skip_screenshots:
            # Use existing img or default img if doesn't exist.
            if not img_path.exists():
                img_path = screenshot_dir / "0_default.png"
        elif not (configuration.skip_existing_screenshots and img_path.exists()):
            if project.homepage == project.github_url:
                # If no dedicated homepage is given (other than the github site),
                # use the default img.
                img_path = screenshot_dir / "0_default.png"
            else:
                # Try to take a screenshot of the website and use default img if that
                # fails.
                try:
                    # TODO: Could make this in parallel, but not really required right
                    #   now.
                    print(
                        f"Taking screenshot for {project.name} (from {project.homepage})"
                    )
                    sleep = configuration.get("wait_before_screenshot", 10)
                    asyncio.run(
                        save_screenshot(project.homepage, img_path, sleep=sleep)
                    )
                    print(f"Success! Saved in: {img_path}")
                except pyppeteer.errors.TimeoutError:
                    print(f"Timeout when loading: {project.homepage}")
                    img_path = screenshot_dir / "0_default.png"

    # TODO: Check that this link opens in new tab from Github readme.
    project_md += f'<br><a href="{project.homepage}"><img width="256" height="144" src="{img_path}"></a><br>'
    project_md += f'<h3><a href="{project.homepage}">{project.name}</a></h3>'

    metrics = []
    if project.created_at:
        project_total_month = best_of.utils.diff_month(
            datetime.now(), project.created_at
        )
        if (
            configuration.project_new_months
            and int(configuration.project_new_months) >= project_total_month
        ):
            metrics.append("🐣 New")
    if project.star_count:
        metrics.append(f"⭐ {str(best_of.utils.simplify_number(project.star_count))}")
    if project.github_url:
        metrics.append(f'<a href="{project.github_url}">:octocat: Code</a>')

    if metrics:
        metrics_str = " · ".join(metrics)
        project_md += f"<p>{metrics_str}</p>"

    description = project.description
    if description[-1] == ".":  # descriptions returned by best-of end with .
        description = description[:-1]
    description = shorten(description, 90)
    project_md += f"<p>{description}</p>"

    if project.github_id:
        author = project.github_id.split("/")[0]
        project_md += (
            f'<p><sup>by <a href="https://github.com/{author}">@{author}</a></sup></p>'
        )

    return project_md


def generate_table_html(projects: list, config: Dict, labels: Dict):
    """Generates a table for several projects."""
    table_html = '<table width="100%">'
    print("Creating table...")
    for project_row in chunker(projects, config.get("projects_per_row", 3)):
        print("New row:")
        table_html += '<tr align="center">'
        for project in project_row:
            print("- " + project.name)
            # table_html += project.name
            project_md = generate_project_html(project, config, labels)
            table_html += f'<td valign="top" width="33.3%">{project_md}</td>'
        table_html += "</tr>"
    table_html += "</table>"
    print()
    return table_html


def generate_category_gallery_md(
    category: Dict, config: Dict, labels: list, title_md_prefix: str = "##"
) -> str:
    """Generates the gallery with all projects for a category."""

    category_md = ""

    if (
        (
            config.hide_empty_categories
            or category.category == best_of.default_config.DEFAULT_OTHERS_CATEGORY_ID
        )
        and not category.projects
        and not category.hidden_projects
    ):
        # Do not show category
        return category_md

    # Set up category header.
    category_md += title_md_prefix + " " + category.title + "\n\n"
    # TODO: Original line doesn't work if there's no TOC. Replaced it with link
    #   to title for now but fix this in original repo.
    # category_md += f'<a href="#contents"><img align="right" width="15" height="15" src="{best_of.default_config.UP_ARROW_IMAGE}" alt="Back to top"></a>\n\n'
    category_md += f'<a href="#----best-of-streamlit----"><img align="right" width="15" height="15" src="{best_of.default_config.UP_ARROW_IMAGE}" alt="Back to top"></a>\n\n'
    if category.subtitle:
        category_md += "_" + category.subtitle.strip() + "_\n\n"

    if category.projects:
        # Show top projects directly (in a html table).
        num_shown = config.get("projects_per_category", 6)
        table_html = generate_table_html(category.projects[:num_shown], config, labels)
        category_md += table_html + "\n\n"

        # Hide other projects in an expander.
        if len(category.projects) > num_shown:
            hidden_table_html = generate_table_html(
                category.projects[num_shown:], config, labels
            )
            category_md += f'<br><details align="center"><summary><b>Show {len(category.projects) - num_shown} more for "{category.title}"</b></summary><br>{hidden_table_html}</details>\n\n'

    # This is actually not used here (because all projects are set to show:
    # True) but it's left here from the original `best_of.generate_category_md` function
    # for completeness.
    if category.hidden_projects:
        category_md += (
            "<details><summary>Show "
            + str(len(category.hidden_projects))
            + " hidden projects...</summary>\n\n"
        )
        for project in category.hidden_projects:
            project_md = best_of.md_generation.generate_project_md(
                project, config, labels, generate_body=False
            )
            category_md += project_md + "\n"
        category_md += "</details>\n"

    return "<br>\n\n" + category_md


def generate_short_toc(categories: OrderedDict, config: Dict) -> str:
    toc_md = "<br>\n\n"
    toc_points = []
    for category in categories:
        category_info = Dict(categories[category])
        if category_info.ignore:
            continue

        url = "#" + best_of.md_generation.process_md_link(category_info.title)

        project_count = 0
        if category_info.projects:
            project_count += len(category_info.projects)
        if category_info.hidden_projects:
            project_count += len(category_info.hidden_projects)

        if not project_count and (
            config.hide_empty_categories
            or category == best_of.default_config.DEFAULT_OTHERS_CATEGORY_ID
        ):
            # only add if more than 0 projects
            continue

        toc_points.append(f"[{category_info.title}]({url})")
    toc_md += " | ".join(toc_points) + "\n\n<br>\n\n"
    return toc_md


def main(
    projects_file: str = typer.Argument(..., help="Path to the projects.yaml file"),
    github_api_key: str = typer.Option(
        "", "--github_api_key", "-g", help="API key for Github"
    ),
):
    """
    Generate README.md from a projects file (YAML).
    """
    # Monkey-path best_of with my custom generation functions.
    best_of.md_generation.generate_category_md = generate_category_gallery_md
    best_of.md_generation.generate_toc = generate_short_toc
    # TODO: Add all original cmd line params here.
    best_of.generator.generate_markdown(projects_file, github_api_key=github_api_key)


if __name__ == "__main__":
    typer.run(main)

