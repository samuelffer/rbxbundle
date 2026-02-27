# rbxbundle

`rbxbundle` is a tool that helps you break down bulky Roblox model files (`.rbxmx`, `.xml`, or `.txt`) into clean, structured parts.

--- 

## Why does this project exist?

If you've ever tried using AI to help you with your script, you've probably noticed that it's difficult to always be specific enough for the AI ​​to interpret. The solution to this would be to use the `.rbxmx` file, but you've ever tried to send a Roblox `.rbxmx` file to an AI (like ChatGPT) to get help with a complex script, you've likely run into a major issue: **Roblox XML is incredibly verbose.**

These files are packed with repetitive tags that consume too many **tokens**, causing the AI to lose context, ignore parts of your code, or hit character limits before providing a useful answer.

`rbxbundle` was created to fix this. It strips away the XML "noise" and organizes your model into a clean bundle. This allows you to provide the AI with only the essential code and structure, saving tokens and getting much better results.

--- 

## What does it do?

*   **Extracts Scripts**: Saves every script as a standalone `.lua` file. No XML clutter, just pure code.
*   **Outlines Structure**: Creates a hierarchy file so the AI understands your model's organization.
*   **Cleans Attributes**: Pulls important item attributes without the original file's overhead.
*   **Maps Dependencies**: Identifies `require()` calls to help the AI understand how your scripts interact.
*   **Zips Everything**: Provides an organized folder and a `.zip` file ready to be uploaded to any AI tool.

--- 

## How to use it?

1.  Place your model file in the `input/` folder.
2.  Run the script:
    ```bash
    python cli.py
    ```
3.  Follow the terminal prompts. Your output will be in the `output/` folder.

--- 

## Requirements

*   Python 3.9+
*   No external dependencies.


## License

MIT License. See [LICENSE](LICENSE) for details.
