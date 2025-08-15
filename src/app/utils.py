import discord


def strip_bot_mention(content: str, message: discord.Message, bot_id: int) -> str:
    for mention in message.mentions:
        if mention.id == bot_id:
            content = content.replace(f"<@{mention.id}>", "").replace(f"<@!{mention.id}>", "")
    return content.strip()


async def send_long_message(channel: discord.TextChannel, content: str) -> None:
    chunks = [content[i : i + 2000] for i in range(0, len(content), 2000)]
    for chunk in chunks:
        await channel.send(chunk)
