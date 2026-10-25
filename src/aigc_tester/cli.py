#!/usr/bin/env python3
"""
Image Generator from Prompt Files or Direct Prompts

This script generates images from text prompt files or direct prompt input using OpenAI's API.
Can be used as a CLI tool or installed via pipx.

Usage:
    # From directory of prompt files
    imgpt generate --dir <prompts_dir> [--output <output_dir>]
    
    # From direct prompt
    imgpt generate "A beautiful sunset over mountains"
    
    # Save to specific file
    imgpt generate "A robot in space" --output robot_space.png
    
    # Configuration management
    imgpt config show
    imgpt config set openai_api_key "your-key-here"
    imgpt config set default_model "dall-e-3"
"""

import os
import sys
import base64
import time
from pathlib import Path
from typing import List, Optional, Annotated

import openai
import typer
from rich.console import Console
from rich.table import Table
from rich import print as rprint

from .config import config_manager, ImageptConfig
from .providers import (
    get_provider,
    GenerationResult,
    VALID_SIZES,
    validate_model_size,
)
from .runner import run_suite
from .review import (
    build_review_sheet,
    find_latest_log,
    load_run_records,
    write_review_sheet,
)
from .report import generate_report

# Initialize Typer app and console
app = typer.Typer(
    name="aigc",
    help="名创优品 AIGC 营销素材测试工具：商品图/IP创意图/视频分镜生成、批量测试与报告",
    rich_markup_mode="rich"
)
config_app = typer.Typer(help="🔧 Configuration management")
app.add_typer(config_app, name="config")

console = Console()





def read_prompt_file(prompt_path: Path) -> str:
    """Read prompt content from a file."""
    with open(prompt_path, 'r', encoding='utf-8') as f:
        content = f.read().strip()
    
    # If it's a markdown file, try to extract description
    if prompt_path.suffix.lower() == '.md':
        lines = content.split('\n')
        description_lines = []
        in_description = False
        
        for line in lines:
            if line.startswith('**Description:**'):
                in_description = True
                continue
            elif in_description and line.startswith('**'):
                break
            elif in_description and line.strip():
                description_lines.append(line.strip())
        
        # If description found, use it; otherwise use cleaned content
        if description_lines:
            return ' '.join(description_lines)
        else:
            # Remove markdown headers and formatting for a cleaner prompt
            clean_lines = []
            for line in lines:
                if not line.startswith('#') and not line.startswith('**') and line.strip():
                    clean_lines.append(line.strip())
            return ' '.join(clean_lines)
    
    return content


def save_image(image_data: bytes, output_path: Path):
    """Save image data to file."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    with open(output_path, 'wb') as f:
        f.write(image_data)
    
    rprint(f"💾 Saved image to [bold blue]{output_path}[/bold blue]")


def find_prompt_files(prompts_dir: Path) -> List[Path]:
    """Find all prompt files in the directory."""
    prompt_files = []
    
    # Look for various prompt file extensions
    extensions = ['.prompt', '.txt', '.md']
    
    for ext in extensions:
        prompt_files.extend(prompts_dir.glob(f"*{ext}"))
    
    return sorted(prompt_files)


def get_output_path(prompt_file: Path, output_dir: Path, output_format: str = "png") -> Path:
    """Get the output path for a prompt file."""
    # Remove the prompt extension and add the output format extension
    base_name = prompt_file.stem
    return output_dir / f"{base_name}.{output_format}"


def get_default_size(model: str) -> str:
    """Get default size for a model."""
    size_defaults = {
        "gpt-image-1": "1536x1024",
        "dall-e-2": "1024x1024",
        "dall-e-3": "1024x1024",
        # 火山 Seedream 5.0 flash 默认用 2K 档位（官方推荐默认值）
        "doubao-seedream-5-0-flash-260915": "2K",
    }
    return size_defaults.get(model, "1536x1024")


@app.command()
def generate(
    prompt: Annotated[Optional[str], typer.Argument(help="Direct prompt text for image generation")] = None,
    dir: Annotated[Optional[str], typer.Option("--dir", help="Directory containing prompt files")] = None,
    output: Annotated[Optional[str], typer.Option("--output", help="Output file path (for direct prompts) or directory (for prompt files)")] = None,
    model: Annotated[Optional[str], typer.Option("--model", help="Model to use for image generation")] = None,
    size: Annotated[Optional[str], typer.Option("--size", help="Image size (e.g., 1024x1024, 1536x1024, 1024x1536)")] = None,
    quality: Annotated[Optional[str], typer.Option("--quality", help="Image quality")] = None,
    style: Annotated[Optional[str], typer.Option("--style", help="Image style for DALL-E 3 (vivid or natural)")] = None,
    format: Annotated[Optional[str], typer.Option("--format", help="Output format")] = None,
    delay: Annotated[Optional[float], typer.Option("--delay", help="Delay between API calls in seconds")] = None,
    skip_existing: Annotated[bool, typer.Option("--skip-existing", help="Skip generating images that already exist")] = False,
    provider_name: Annotated[str, typer.Option("--provider", help="模型提供方：mock（离线模拟，默认）/ openai（真实调用）/ ark（火山豆包）")] = "mock",
    reference: Annotated[Optional[str], typer.Option("--reference", help="参考图路径（图生图，保证商品/IP一致性）")] = None,
):
    """🎨 生成图片（支持单条提示词，或从文件夹批量生成）。"""
    
    # Load configuration and apply defaults
    config = config_manager.load_config()

    # 各 provider 的默认模型（用户没显式传 --model 时用）
    default_models = {
        "ark": "doubao-seedream-5-0-flash-260915",
        "doubao": "doubao-seedream-5-0-flash-260915",
        "openai": config.default_model,
        "mock": config.default_model,
    }
    model = model or default_models.get(provider_name, config.default_model)
    size = size or config.default_size or get_default_size(model)
    quality = quality or config.default_quality
    style = style or config.default_style
    format = format or config.default_format
    delay = delay if delay is not None else config.default_delay
    skip_existing = skip_existing or config.skip_existing
    
    # Validate inputs
    if not prompt and not dir:
        rprint("❌ Error: Must provide either a prompt or a directory with --dir")
        raise typer.Exit(1)
    
    if prompt and dir:
        rprint("❌ Error: Cannot use both direct prompt and directory mode")
        raise typer.Exit(1)
    
    # Validate model and size compatibility
    if not validate_model_size(model, size):
        rprint(f"❌ Error: Size '{size}' is not valid for model '{model}'")
        rprint(f"Valid sizes for {model}: {', '.join(VALID_SIZES[model])}")
        raise typer.Exit(1)
    
    rprint("🤖 [bold]AIGC 营销素材测试工具[/bold]")
    rprint("=" * 50)

    # 初始化 provider（mock 离线模式不需要 API Key）
    try:
        if provider_name in ("ark", "doubao"):
            api_key = config.ark_api_key or os.getenv("ARK_API_KEY") or os.getenv("ark_api_key") or os.getenv("AIGC_API")
        else:
            api_key = config.openai_api_key or os.getenv("OPENAI_API_KEY")
        provider = get_provider(provider_name, api_key)
        rprint(f"✅ Provider 已就绪：[cyan]{provider.name}[/cyan]")
    except Exception as e:
        rprint(f"❌ Provider 初始化失败：{e}")
        raise typer.Exit(1)
    
    # Handle directory mode
    if dir:
        prompts_dir = Path(dir)
        output_dir = Path(output) if output else (Path(config.default_output_dir) if config.default_output_dir else prompts_dir)
        
        if not prompts_dir.exists():
            rprint(f"❌ Prompts directory does not exist: {prompts_dir}")
            raise typer.Exit(1)
        
        if not prompts_dir.is_dir():
            rprint(f"❌ Prompts path is not a directory: {prompts_dir}")
            raise typer.Exit(1)
        
        rprint(f"📁 Prompts directory: [bold blue]{prompts_dir}[/bold blue]")
        rprint(f"📂 Output directory: [bold blue]{output_dir}[/bold blue]")
        
        # Find all prompt files
        prompt_files = find_prompt_files(prompts_dir)
        if not prompt_files:
            rprint(f"❌ No prompt files found in {prompts_dir}")
            rprint("Looking for files with extensions: .prompt, .txt, .md")
            raise typer.Exit(1)
        
        rprint(f"📁 Found [bold]{len(prompt_files)}[/bold] prompt files")
        
        # Generate images for each prompt file
        success_count = 0
        for prompt_file in prompt_files:
            try:
                output_path = get_output_path(prompt_file, output_dir, format)
                
                # Skip if image already exists and --skip-existing is set
                if skip_existing and output_path.exists():
                    rprint(f"⏭️  Skipping [dim]{prompt_file.name}[/dim] (image already exists)")
                    continue
                
                # Read prompt
                file_prompt = read_prompt_file(prompt_file)
                if not file_prompt.strip():
                    rprint(f"⚠️  Skipping [dim]{prompt_file.name}[/dim] (empty prompt)")
                    continue
                
                # Generate image
                result = provider.generate(
                    file_prompt, model=model, size=size, quality=quality,
                    style=style, output_format=format,
                    references=[reference] if reference else None
                )
                image_data = result.image_data
                
                # Save image
                save_image(image_data, output_path)
                success_count += 1
                
                # Rate limiting - be respectful to the API
                if delay > 0:
                    time.sleep(delay)
                
            except Exception as e:
                rprint(f"❌ Failed to process {prompt_file.name}: {e}")
                continue
        
        rprint(f"\n🎉 [bold green]Image generation complete![/bold green]")
        rprint(f"✅ Successfully generated [bold]{success_count}/{len(prompt_files)}[/bold] images")
        rprint(f"📂 Images saved to: [bold blue]{output_dir}[/bold blue]")
    
    # Handle direct prompt mode
    else:
        if output:
            output_path = Path(output)
            # Ensure correct extension for output format
            expected_ext = f".{format}"
            if output_path.suffix.lower() != expected_ext:
                output_path = output_path.with_suffix(expected_ext)
        else:
            # Use default output directory if configured
            output_dir = Path(config.default_output_dir) if config.default_output_dir else Path.cwd()
            # Generate filename from prompt
            safe_name = "".join(c for c in prompt[:30] if c.isalnum() or c in (' ', '-', '_')).rstrip()
            safe_name = safe_name.replace(' ', '_').lower()
            output_path = output_dir / f"{safe_name}.{format}"
        
        rprint(f"📝 Prompt: [dim]{prompt}[/dim]")
        rprint(f"📂 Output: [bold blue]{output_path}[/bold blue]")
        
        try:
            # Generate image
            result = provider.generate(
                prompt, model=model, size=size, quality=quality,
                style=style, output_format=format,
                references=[reference] if reference else None
            )
            image_data = result.image_data
            
            # Save image
            save_image(image_data, output_path)
            
            rprint(f"\n🎉 [bold green]Image generation complete![/bold green]")
            rprint(f"📂 Image saved to: [bold blue]{output_path}[/bold blue]")
            
        except Exception as e:
            rprint(f"❌ Failed to generate image: {e}")
            raise typer.Exit(1)


@config_app.command("show")
def config_show():
    """📋 Show current configuration."""
    config_manager.show_config()


@config_app.command("set")
def config_set(
    key: Annotated[str, typer.Argument(help="Configuration key to set")],
    value: Annotated[str, typer.Argument(help="Configuration value to set")]
):
    """⚙️ Set a configuration value."""
    try:
        # Convert string values to appropriate types
        if key in ["default_delay"]:
            value = float(value)
        elif key in ["skip_existing"]:
            value = value.lower() in ["true", "1", "yes", "on"]
        
        config_manager.update_config(**{key: value})
        rprint(f"✅ Set [bold]{key}[/bold] = [cyan]{value}[/cyan]")
    except Exception as e:
        rprint(f"❌ Failed to set configuration: {e}")
        raise typer.Exit(1)


@config_app.command("reset")
def config_reset():
    """🔄 Reset configuration to defaults."""
    if typer.confirm("Are you sure you want to reset all configuration to defaults?"):
        config_manager.reset_config()
        rprint("✅ Configuration reset to defaults")
    else:
        rprint("❌ Configuration reset cancelled")


@config_app.command("path")
def config_path():
    """📁 Show configuration file path."""
    rprint(f"📄 Configuration file: [bold blue]{config_manager.config_file}[/bold blue]")


@app.command()
def run(
    suite: Annotated[str, typer.Option("--suite", help="测试套件 YAML 路径")] = "testcases/smoke.yaml",
    output_dir: Annotated[str, typer.Option("--output-dir", help="生成结果目录")] = "outputs",
    logs_dir: Annotated[str, typer.Option("--logs-dir", help="日志目录")] = "logs",
):
    """📋 批量执行测试套件（逐轮生成、自动记录日志）。"""
    # 不传统一 key：由 runner._resolve_key 按每条用例的 provider 分别解析
    # （ark 用 ark key，openai 用 openai key），避免把 OpenAI key 误传给火山

    rprint("🧪 [bold]批量执行测试套件[/bold]")
    rprint("=" * 50)
    rprint(f"📁 套件：[cyan]{suite}[/cyan]")

    summary = run_suite(
        suite,
        output_dir=output_dir,
        logs_dir=logs_dir,
    )

    # 结果表格
    table = Table(title=f"执行结果（run_id: {summary['run_id']}）")
    table.add_column("用例ID")
    table.add_column("轮次")
    table.add_column("场景")
    table.add_column("状态")
    table.add_column("耗时ms")
    table.add_column("输出 / 错误")
    for r in summary["records"]:
        status = r["status"]
        icon = {
            "success": "✅ success",
            "failed": "❌ failed",
            "skipped": "⏭️ skipped",
        }[status]
        detail = r.get("output") or r.get("error") or ""
        table.add_row(
            r["case_id"],
            str(r.get("round", "-")),
            r.get("scene", ""),
            icon,
            str(r.get("latency_ms", "-")),
            detail,
        )
    console.print(table)

    rprint(
        f"\n📊 汇总：总数 [bold]{summary['total']}，"
        f"成功 [green]{summary['success']}，"
        f"失败 [red]{summary['failed']}，"
        f"跳过 [yellow]{summary['skipped']}"
    )
    rprint(f"📄 日志：[bold blue]{summary['log_path']}[/bold blue]")


@app.command()
def video(
    prompt: Annotated[str, typer.Argument(help="视频生成提示词（可用分镜模板填好）")],
    output: Annotated[str, typer.Option("--output", help="输出文件路径（.gif）")] = "outputs/video.gif",
    provider_name: Annotated[str, typer.Option("--provider", help="模型提供方：mock（默认）")] = "mock",
    size: Annotated[str, typer.Option("--size", help="画面比例：9:16 / 16:9 / 1:1")] = "9:16",
    duration: Annotated[int, typer.Option("--duration", help="视频时长（秒）")] = 5,
):
    """🎬 生成视频（mock 模式输出占位 GIF，真实模型后续接入）。"""
    config = config_manager.load_config()
    api_key = config.openai_api_key or os.getenv("OPENAI_API_KEY")

    rprint("🎬 [bold]视频生成[/bold]")
    rprint("=" * 50)

    try:
        provider = get_provider(provider_name, api_key)
        result = provider.generate_video(
            prompt,
            model="seedance",
            size=size,
            duration=duration,
        )
        output_path = Path(output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "wb") as f:
            f.write(result.video_data)
    except Exception as e:
        rprint(f"❌ 视频生成失败：{e}")
        raise typer.Exit(1)

    rprint(f"💾 视频已保存：[bold blue]{output}[/bold blue]（耗时 {result.latency_ms}ms）")


@app.command()
def review(
    latest: Annotated[bool, typer.Option("--latest", help="依据最近一次运行结果生成打分表")] = True,
    logs_dir: Annotated[str, typer.Option("--logs-dir", help="日志目录")] = "logs",
    reviews_dir: Annotated[str, typer.Option("--reviews-dir", help="打分表目录")] = "reviews",
):
    """📝 生成复核打分表（YAML，填好 1~5 分后用于报告）。"""
    log_file = find_latest_log(logs_dir)
    if log_file is None:
        rprint("❌ 未找到运行日志，请先执行：aigc run")
        raise typer.Exit(1)

    records = load_run_records(log_file)
    run_id = records[0]["run_id"]
    sheet = build_review_sheet(records, run_id)
    path = write_review_sheet(sheet, reviews_dir)

    rprint(f"📝 打分表已生成：[bold blue]{path}[/bold blue]")
    rprint(f"   共 {len(sheet['reviews'])} 条待复核记录（已预填示例分数）")
    rprint("   请在文件中修改各项分数和问题，然后执行：[bold]aigc report --latest[/bold]")


@app.command()
def report(
    latest: Annotated[bool, typer.Option("--latest", help="依据最近一次运行生成报告")] = True,
    log: Annotated[Optional[str], typer.Option("--log", help="指定运行日志路径")] = None,
    reports_dir: Annotated[str, typer.Option("--reports-dir", help="报告目录")] = "reports",
):
    """📊 生成自包含 HTML 测试报告（含通过率、维度均分、问题清单、回归对比）。"""
    try:
        info = generate_report(log_path=log, reports_dir=reports_dir)
    except FileNotFoundError as e:
        rprint(f"❌ {e}")
        raise typer.Exit(1)

    rprint("📊 [bold]HTML 测试报告已生成[/bold]")
    rprint(f"📄 报告文件：[bold blue]{info['html_path']}[/bold blue]")
    rprint(f"🔧 打分表：{'已包含' if info['has_reviews'] else '未找到，仅按执行结果生成'}")
    rprint("💡 直接用浏览器打开报告文件即可查看和分享")


@app.command()
def version():
    """📋 显示版本信息。"""
    rprint("🛍️ [bold]miniso-aigc-tester[/bold] v1.0.0")
    rprint("品牌营销AIGC素材（商品图/IP创意图/视频分镜/短视频）测试工具 · CLI + Streamlit 双形态")
    rprint("AI创新部实习项目")


def main():
    """Main entry point for the CLI."""
    app()


if __name__ == "__main__":
    main() 