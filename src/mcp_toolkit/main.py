from fastmcp import FastMCP,tools

mcp = FastMCP()


@mcp.tool()
def hello_mcp(name:str):
    return f"Hello {name}!!!"

if __name__ == "__main__":
    mcp.run()