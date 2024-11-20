import os
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional, List, Dict, Any
from rich.logging import RichHandler
import typer
from rich.console import Console
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TimeElapsedColumn
from rich.table import Table
from rich.traceback import install

from .converter import ZenhubRAGConverter
from .models import RAGDocument
from .processors.openai_processor import OpenAIProcessor
from .exceptions import ZenhubAPIError, ConversionError, ProcessingError

# Install rich traceback handler
install(show_locals=True)

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(message)s",
    datefmt="[%X]",
    handlers=[RichHandler(rich_tracebacks=True)]
)

logger = logging.getLogger("zenhub-to-rag")

# Create Typer app
app = typer.Typer(
    help="Convert Zenhub data to RAG-optimized format",
    add_completion=False
)
console = Console()

def setup_output_dir(output_dir: Path) -> None:
    """Setup output directory with logs and data folders."""
    try:
        output_dir.mkdir(parents=True, exist_ok=True)
        (output_dir / "logs").mkdir(exist_ok=True)
        (output_dir / "data").mkdir(exist_ok=True)
    except Exception as e:
        raise ProcessingError(f"Failed to create output directories: {str(e)}")

def validate_token(
    ctx: typer.Context, 
    token: Optional[str], 
    env_var: str,
    error_message: str
) -> Optional[str]:
    """Validate token from CLI or environment."""
    if token:
        return token
    env_token = os.getenv(env_var)
    if env_token:
        return env_token
    console.print(Panel(
        error_message,
        title="Error",
        style="red"
    ))
    ctx.exit(1)
    return None

@app.command()
def inspect(
    ctx: typer.Context,
    workspace_id: str = typer.Argument(..., help="Zenhub workspace identifier"),
    access_token: Optional[str] = typer.Option(
        None,
        "--access-token",
        "-t",
        help="Zenhub API access token. Can also be set via ZENHUB_TOKEN environment variable.",
        envvar="ZENHUB_TOKEN"
    ),
    output_dir: Path = typer.Option(
        Path("output"),
        "--output-dir",
        "-o",
        help="Output directory for inspection results"
    ),
) -> None:
    """Inspect a Zenhub workspace and show detailed content analysis."""
    try:
        # Validate token
        token = validate_token(
            ctx, 
            access_token, 
            "ZENHUB_TOKEN",
            "No Zenhub access token provided. Please provide via --access-token or set ZENHUB_TOKEN environment variable."
        )

        # Setup output directory
        setup_output_dir(output_dir)
        
        # Setup logging
        log_file = output_dir / "logs" / f"inspect_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
        file_handler = logging.FileHandler(log_file)
        logger.addHandler(file_handler)
        
        converter = ZenhubRAGConverter(token)
        
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TimeElapsedColumn(),
            console=console
        ) as progress:
            # Fetch workspace content
            task = progress.add_task("Fetching workspace content...", total=None)
            workspace_data = converter.get_workspace_data(workspace_id)
            progress.update(task, completed=True)
            
            # Extract content
            task = progress.add_task("Analyzing content...", total=None)
            
            # Collect statistics
            stats = {
                "total_issues": 0,
                "pipelines": {},
                "epics": {},
                "labels": {},
                "sprints": {},
                "estimate_distribution": {},
                "dependencies_count": 0,
                "assigned_issues": 0,
                "unassigned_issues": 0
            }
            
            # Process issues
            for issue in workspace_data["issues"]:
                stats["total_issues"] += 1
                
                # Pipeline stats
                pipeline = issue.get("pipeline", {}).get("name", "No Pipeline")
                stats["pipelines"][pipeline] = stats["pipelines"].get(pipeline, 0) + 1
                
                # Epic stats
                if "epic" in issue:
                    epic_name = issue["epic"].get("title", "Unknown Epic")
                    stats["epics"][epic_name] = stats["epics"].get(epic_name, 0) + 1
                
                # Label stats
                for label in issue.get("labels", []):
                    label_name = label["name"]
                    stats["labels"][label_name] = stats["labels"].get(label_name, 0) + 1
                
                # Sprint stats
                if "sprint" in issue:
                    sprint_name = issue["sprint"].get("title", "Unknown Sprint")
                    stats["sprints"][sprint_name] = stats["sprints"].get(sprint_name, 0) + 1
                
                # Estimate stats
                estimate = issue.get("estimate", {}).get("value", "No Estimate")
                stats["estimate_distribution"][str(estimate)] = \
                    stats["estimate_distribution"].get(str(estimate), 0) + 1
                
                # Dependencies
                if issue.get("dependencies", []):
                    stats["dependencies_count"] += len(issue["dependencies"])
                
                # Assignment stats
                if issue.get("assignees", []):
                    stats["assigned_issues"] += 1
                else:
                    stats["unassigned_issues"] += 1
            
            progress.update(task, completed=True)
        
        # Create summary tables
        issues_table = Table(title="Issues Summary")
        issues_table.add_column("Metric", style="cyan")
        issues_table.add_column("Count", style="green")
        
        issues_table.add_row("Total Issues", str(stats["total_issues"]))
        issues_table.add_row("Assigned Issues", str(stats["assigned_issues"]))
        issues_table.add_row("Unassigned Issues", str(stats["unassigned_issues"]))
        issues_table.add_row("Total Dependencies", str(stats["dependencies_count"]))
        
        pipeline_table = Table(title="Pipeline Distribution")
        pipeline_table.add_column("Pipeline", style="cyan")
        pipeline_table.add_column("Issues", style="green")
        for pipeline, count in stats["pipelines"].items():
            pipeline_table.add_row(pipeline, str(count))
        
        epic_table = Table(title="Epic Distribution")
        epic_table.add_column("Epic", style="cyan")
        epic_table.add_column("Issues", style="green")
        for epic, count in stats["epics"].items():
            epic_table.add_row(epic, str(count))
        
        label_table = Table(title="Label Distribution")
        label_table.add_column("Label", style="cyan")
        label_table.add_column("Count", style="green")
        for label, count in stats["labels"].items():
            label_table.add_row(label, str(count))
        
        # Print results
        console.print(Panel(
            "✅ Analysis Complete",
            title="Success",
            style="green"
        ))
        
        console.print(issues_table)
        console.print(pipeline_table)
        console.print(epic_table)
        console.print(label_table)
        
        # Save analysis
        analysis_file = output_dir / "data" / f"analysis_{workspace_id}.json"
        with open(analysis_file, 'w') as f:
            json.dump(stats, f, indent=2)
            
        logger.info(f"Analysis saved to {analysis_file}")
        
    except Exception as e:
        logger.error(f"Inspection failed: {str(e)}", exc_info=True)
        console.print(Panel(
            f"❌ Failed to inspect workspace: {str(e)}",
            title="Error",
            style="red"
        ))
        raise typer.Exit(1)
    finally:
        if 'file_handler' in locals():
            logger.removeHandler(file_handler)

@app.command()
def convert(
    ctx: typer.Context,
    workspace_id: str = typer.Argument(..., help="Zenhub workspace identifier"),
    access_token: Optional[str] = typer.Option(
        None,
        "--access-token",
        "-t",
        help="Zenhub API access token. Can also be set via ZENHUB_TOKEN environment variable.",
        envvar="ZENHUB_TOKEN"
    ),
    output_dir: Path = typer.Option(
        Path("output"),
        "--output-dir",
        "-o",
        help="Output directory"
    ),
    pipeline_filter: Optional[List[str]] = typer.Option(
        None,
        "--pipeline",
        "-p",
        help="Filter by pipeline name"
    ),
    label_filter: Optional[List[str]] = typer.Option(
        None,
        "--label",
        "-l",
        help="Filter by label"
    ),
    include_epics: bool = typer.Option(
        True,
        "--epics/--no-epics",
        help="Include epic information"
    ),
    include_dependencies: bool = typer.Option(
        True,
        "--dependencies/--no-dependencies",
        help="Include dependency information"
    ),
    verbose: bool = typer.Option(
        False,
        "--verbose",
        "-v",
        help="Show detailed processing information"
    )
) -> None:
    """Convert Zenhub content to RAG-optimized format."""
    try:
        # Validate token
        token = validate_token(
            ctx, 
            access_token, 
            "ZENHUB_TOKEN",
            "No Zenhub access token provided. Please provide via --access-token or set ZENHUB_TOKEN environment variable."
        )
        
        # Setup output directory
        setup_output_dir(output_dir)
        
        # Setup logging
        log_file = output_dir / "logs" / f"convert_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
        file_handler = logging.FileHandler(log_file)
        logger.addHandler(file_handler)
        
        if verbose:
            logger.setLevel(logging.DEBUG)
        
        converter = ZenhubRAGConverter(token)
        output_file = output_dir / "data" / f"{workspace_id}_raw.jsonl"
        
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TimeElapsedColumn(),
            console=console
        ) as progress:
            task = progress.add_task("Converting workspace data...", total=None)
            
            # Process workspace with filters
            documents = converter.process_workspace(
                workspace_id,
                pipeline_filter=pipeline_filter,
                label_filter=label_filter,
                include_epics=include_epics,
                include_dependencies=include_dependencies
            )
            
            if verbose:
                for doc in documents:
                    logger.debug(f"Processed: {doc.metadata.get('title', 'Untitled')}")
            
            # Save documents
            converter.save_to_jsonl(documents, output_file)
            progress.update(task, completed=True)
        
        console.print(Panel(
            f"Successfully converted {len(documents)} items to {output_file}",
            title="Success",
            style="green"
        ))
        
    except Exception as e:
        logger.error(f"Conversion failed: {str(e)}", exc_info=True)
        console.print(Panel(
            f"❌ Failed to convert workspace: {str(e)}",
            title="Error",
            style="red"
        ))
        raise typer.Exit(1)
    finally:
        if 'file_handler' in locals():
            logger.removeHandler(file_handler)

@app.command()
def help_token() -> None:
    """Show help about getting the required API tokens."""
    help_text = """
Zenhub API Token:
1. Log in to Zenhub (https://app.zenhub.com)
2. Go to Settings → App Settings
3. Click on "API Tokens" in the left sidebar
4. Click "Create new token"
5. Give it a name (e.g., "RAG Converter")
6. Copy the token immediately (you won't see it again!)

Workspace ID:
The workspace ID can be found in your Zenhub URL:
https://app.zenhub.com/workspaces/WORKSPACE_ID/board

Environment Variables:
You can set this environment variable instead of passing it as an argument:
export ZENHUB_TOKEN=your_token_here

Workflow Example:
1. First inspect the workspace:
   zenhub-to-rag inspect your_workspace_id

2. Convert to RAG format:
   zenhub-to-rag convert your_workspace_id --output-dir ./output

3. Filter by pipeline:
   zenhub-to-rag convert your_workspace_id --pipeline "Sprint Backlog" "In Progress"

4. Filter by label:
   zenhub-to-rag convert your_workspace_id --label bug feature

5. Exclude epics or dependencies:
   zenhub-to-rag convert your_workspace_id --no-epics --no-dependencies
"""
    console.print(Panel(help_text, title="Getting Started", style="blue"))

@app.command()
def validate(
    ctx: typer.Context,
    input_file: Path = typer.Argument(..., help="Processed JSONL file to validate")
) -> None:
    """Validate processed RAG documents."""
    try:
        if not input_file.exists():
            raise ProcessingError(f"Input file not found: {input_file}")
        
        validation_errors = []
        processed_count = 0
        
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TimeElapsedColumn(),
            console=console
        ) as progress:
            task = progress.add_task("Validating documents...", total=None)
            
            with open(input_file, 'r') as f:
                for line_num, line in enumerate(f, 1):
                    try:
                        doc_data = json.loads(line)
                        RAGDocument(**doc_data)
                        processed_count += 1
                    except Exception as e:
                        validation_errors.append({
                            "line": line_num,
                            "error": str(e)
                        })
            
            progress.update(task, completed=True)
        
        if validation_errors:
            console.print(Panel(
                f"Found {len(validation_errors)} validation errors",
                title="Warning",
                style="yellow"
            ))
            
            error_table = Table(title="Validation Errors")
            error_table.add_column("Line", style="cyan")
                       error_table.add_column("Line", style="cyan")
            error_table.add_column("Error", style="red")
            
            for error in validation_errors:
                error_table.add_row(str(error["line"]), error["error"])
            
            console.print(error_table)
        else:
            console.print(Panel(
                f"All {processed_count} documents are valid!",
                title="Success",
                style="green"
            ))
        
    except Exception as e:
        logger.error(f"Validation failed: {str(e)}", exc_info=True)
        console.print(Panel(
            f"❌ Failed to validate documents: {str(e)}",
            title="Error",
            style="red"
        ))
        raise typer.Exit(1)

@app.command()
def stats(
    ctx: typer.Context,
    input_file: Path = typer.Argument(..., help="Processed JSONL file to analyze"),
    output_file: Optional[Path] = typer.Option(
        None,
        "--output",
        "-o",
        help="Output file for statistics (JSON format)"
    )
) -> None:
    """Generate statistics about processed RAG documents."""
    try:
        if not input_file.exists():
            raise ProcessingError(f"Input file not found: {input_file}")
        
        stats_data = {
            "total_documents": 0,
            "pipelines": {},
            "epics": {},
            "labels": set(),
            "sprints": set(),
            "estimate_ranges": {},
            "dependencies": {
                "total": 0,
                "issues_with_deps": 0
            },
            "assignees": set(),
            "content_stats": {
                "avg_length": 0,
                "total_length": 0
            }
        }
        
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TimeElapsedColumn(),
            console=console
        ) as progress:
            task = progress.add_task("Analyzing documents...", total=None)
            
            with open(input_file, 'r') as f:
                for line in f:
                    try:
                        doc = json.loads(line)
                        
                        # Count documents
                        stats_data["total_documents"] += 1
                        
                        # Pipeline stats
                        pipeline = doc["metadata"].get("pipeline", "Unknown")
                        stats_data["pipelines"][pipeline] = stats_data["pipelines"].get(pipeline, 0) + 1
                        
                        # Epic stats
                        epic = doc["metadata"].get("epic")
                        if epic:
                            stats_data["epics"][epic] = stats_data["epics"].get(epic, 0) + 1
                        
                        # Labels
                        stats_data["labels"].update(doc["metadata"].get("labels", []))
                        
                        # Sprints
                        sprint = doc["metadata"].get("sprint")
                        if sprint:
                            stats_data["sprints"].add(sprint)
                        
                        # Estimates
                        estimate = doc["metadata"].get("estimate")
                        if estimate is not None:
                            estimate_range = f"{int(estimate)}-{int(estimate) + 1}"
                            stats_data["estimate_ranges"][estimate_range] = \
                                stats_data["estimate_ranges"].get(estimate_range, 0) + 1
                        
                        # Dependencies
                        deps = doc["metadata"].get("dependencies", [])
                        if deps:
                            stats_data["dependencies"]["total"] += len(deps)
                            stats_data["dependencies"]["issues_with_deps"] += 1
                        
                        # Assignees
                        stats_data["assignees"].update(doc["metadata"].get("assignees", []))
                        
                        # Content stats
                        content_length = len(doc["content"])
                        stats_data["content_stats"]["total_length"] += content_length
                        
                    except Exception as e:
                        logger.warning(f"Error processing document: {str(e)}")
                        continue
            
            progress.update(task, completed=True)
        
        # Calculate averages
        if stats_data["total_documents"] > 0:
            stats_data["content_stats"]["avg_length"] = \
                stats_data["content_stats"]["total_length"] / stats_data["total_documents"]
        
        # Convert sets to lists for JSON serialization
        stats_data["labels"] = list(stats_data["labels"])
        stats_data["sprints"] = list(stats_data["sprints"])
        stats_data["assignees"] = list(stats_data["assignees"])
        
        # Create statistics tables
        overview_table = Table(title="Document Overview")
        overview_table.add_column("Metric", style="cyan")
        overview_table.add_column("Value", style="green")
        
        overview_table.add_row("Total Documents", str(stats_data["total_documents"]))
        overview_table.add_row("Average Content Length", f"{stats_data['content_stats']['avg_length']:.2f} characters")
        overview_table.add_row("Issues with Dependencies", str(stats_data["dependencies"]["issues_with_deps"]))
        overview_table.add_row("Total Dependencies", str(stats_data["dependencies"]["total"]))
        overview_table.add_row("Total Labels", str(len(stats_data["labels"])))
        overview_table.add_row("Total Assignees", str(len(stats_data["assignees"])))
        
        pipeline_table = Table(title="Pipeline Distribution")
        pipeline_table.add_column("Pipeline", style="cyan")
        pipeline_table.add_column("Issues", style="green")
        for pipeline, count in stats_data["pipelines"].items():
            pipeline_table.add_row(pipeline, str(count))
        
        epic_table = Table(title="Epic Distribution")
        epic_table.add_column("Epic", style="cyan")
        epic_table.add_column("Issues", style="green")
        for epic, count in stats_data["epics"].items():
            epic_table.add_row(epic, str(count))
        
        estimate_table = Table(title="Estimate Distribution")
        estimate_table.add_column("Range", style="cyan")
        estimate_table.add_column("Count", style="green")
        for range_key, count in stats_data["estimate_ranges"].items():
            estimate_table.add_row(range_key, str(count))
        
        # Print tables
        console.print(overview_table)
        console.print(pipeline_table)
        console.print(epic_table)
        console.print(estimate_table)
        
        # Save statistics if output file specified
        if output_file:
            with open(output_file, 'w') as f:
                json.dump(stats_data, f, indent=2)
            console.print(Panel(
                f"Statistics saved to {output_file}",
                title="Success",
                style="green"
            ))
        
    except Exception as e:
        logger.error(f"Statistics generation failed: {str(e)}", exc_info=True)
        console.print(Panel(
            f"❌ Failed to generate statistics: {str(e)}",
            title="Error",
            style="red"
        ))
        raise typer.Exit(1)

def main():
    """Entry point for the CLI."""
    try:
        app()
    except KeyboardInterrupt:
        console.print("\n❌ Operation cancelled by user", style="yellow")
        raise typer.Exit(130)
    except Exception as e:
        console.print(f"❌ Unexpected error: {str(e)}", style="red")
        logger.error("Unexpected error", exc_info=True)
        raise typer.Exit(1)

if __name__ == "__main__":
    main() 
