import csv
import os

def format_number(num):
    """Format numbers with K/M suffix for better readability"""
    try:
        num = int(num)
        if num >= 1000000:
            return f"{num/1000000:.1f}M"
        elif num >= 1000:
            return f"{num/1000:.1f}K"
        return str(num)
    except:
        return num

def csv_to_markdown(csv_file, output_file):
    """Convert CSV to markdown table with formatted numbers"""
    with open(csv_file, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        headers = reader.fieldnames
        rows = list(reader)

    # Calculate column widths (min 10, max 50 characters)
    col_widths = {header: max(10, min(50, max(
        len(header),
        max(len(str(row[header])) for row in rows)
    ))) for header in headers}

    # Create markdown table
    with open(output_file, 'w', encoding='utf-8') as f:
        # Write title
        f.write("# TikTok Video Metadata\n\n")
        
        # Write table headers
        header_row = "| " + " | ".join(header.replace('_', ' ').title().ljust(col_widths[header]) for header in headers) + " |"
        separator = "|" + "|".join("-" * (col_widths[header] + 2) for header in headers) + "|"
        
        f.write(header_row + "\n")
        f.write(separator + "\n")

        # Write rows with formatted numbers
        for row in rows:
            formatted_row = []
            for header in headers:
                value = row[header]
                if header in ['view_count', 'like_count', 'repost_count', 'comment_count']:
                    value = format_number(value)
                formatted_row.append(str(value).ljust(col_widths[header]))
            f.write("| " + " | ".join(formatted_row) + " |\n")

        # Write summary
        f.write(f"\n## Summary\n")
        f.write(f"- Total Videos: {len(rows)}\n")
        f.write(f"- Total Views: {format_number(sum(int(row['view_count']) for row in rows))}\n")
        f.write(f"- Total Likes: {format_number(sum(int(row['like_count']) for row in rows))}\n")
        f.write(f"- Total Comments: {format_number(sum(int(row['comment_count']) for row in rows))}\n")
        f.write(f"- Total Reposts: {format_number(sum(int(row['repost_count']) for row in rows))}\n")
        
        # Calculate engagement rate (likes + comments + reposts / views)
        total_views = sum(int(row['view_count']) for row in rows)
        total_engagement = sum(int(row['like_count']) + int(row['comment_count']) + int(row['repost_count']) for row in rows)
        engagement_rate = (total_engagement / total_views) * 100 if total_views > 0 else 0
        f.write(f"- Average Engagement Rate: {engagement_rate:.1f}%\n")

if __name__ == "__main__":
    base_dir = "/Users/stevewitmer/Desktop/Youtube/youtube_downloader/For Sarah"
    csv_file = os.path.join(base_dir, "video_metadata.csv")
    output_file = os.path.join(base_dir, "video_metadata.md")
    csv_to_markdown(csv_file, output_file)
    print(f"Created markdown file: {output_file}") 