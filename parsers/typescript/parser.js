const fs = require('fs');
const path = require('path');
const ts = require('typescript');

function getLineInfo(sourceFile, position) {
    const { line } = sourceFile.getLineAndCharacterOfPosition(position);
    return line + 1; // Convert to 1-based line number
}

function createChunk(sourceFile, node, moduleName, modulePath, type, name) {
    const startPos = node.pos;
    const endPos = node.end - 1; // Exclusive end

    const startLine = getLineInfo(sourceFile, startPos);
    const endLine = getLineInfo(sourceFile, endPos);

    const content = sourceFile.text.slice(startPos, node.end);

    return {
        id: `${modulePath}.${name}`,
        source: sourceFile.fileName,
        module: modulePath,
        name,
        content,
        start_line: startLine,
        end_line: endLine,
        type,
    };
}

async function parseFile(filePath) {
    const fileContent = fs.readFileSync(filePath, 'utf-8');
    const sourceFile = ts.createSourceFile(
        filePath,
        fileContent,
        ts.ScriptTarget.Latest,
        true
    );

    const moduleName = path.basename(filePath, path.extname(filePath));
    const modulePath = path
        .dirname(filePath)
        .split(path.sep)
        .join('.') + '.' + moduleName;

    const chunks = [];
    const dependencies = [];

    // File chunk
    const totalLines = sourceFile.getLineStarts().length;
    chunks.push({
        id: modulePath,
        source: filePath,
        module: modulePath,
        name: null,
        content: fileContent,
        start_line: 1,
        end_line: totalLines,
        type: 'file',
    });

    // Process imports
    const importsNodes = sourceFile.statements.filter(
        (n) => n.kind === ts.SyntaxKind.ImportDeclaration
    );
    if (importsNodes.length > 0) {
        const importCode = importsNodes
            .map((n) => sourceFile.text.slice(n.pos, n.end))
            .join('\n');
        const startLine = getLineInfo(sourceFile, importsNodes[0].pos);
        const endLine = getLineInfo(
            sourceFile,
            importsNodes[importsNodes.length - 1].end - 1
        );
        chunks.push({
            id: `${modulePath}._imports_`,
            source: filePath,
            module: modulePath,
            name: '_imports_',
            content: importCode,
            start_line: startLine,
            end_line: endLine,
            type: 'imports',
        });
    }

    // Process declarations
    const declarations = sourceFile.statements.filter(
        (n) => n.kind !== ts.SyntaxKind.ImportDeclaration
    );

    const declarationChunks = [];
    declarations.forEach((node) => {
        let name, type;
        switch (node.kind) {
            case ts.SyntaxKind.FunctionDeclaration:
                name = node.name?.text || `line${getLineInfo(sourceFile, node.pos)}`;
                type = 'function';
                break;
            case ts.SyntaxKind.ClassDeclaration:
                name = node.name?.text || `line${getLineInfo(sourceFile, node.pos)}`;
                type = 'class';
                break;
            case ts.SyntaxKind.VariableStatement:
                const varDecl = node.declarationList.declarations[0];
                name = varDecl.name.text || `line${getLineInfo(sourceFile, node.pos)}`;
                type = 'variable';
                break;
            default:
                name = `line${getLineInfo(sourceFile, node.pos)}`;
                type = 'other';
                break;
        }

        const chunk = createChunk(
            sourceFile,
            node,
            moduleName,
            modulePath,
            type,
            name
        );
        declarationChunks.push(chunk);
    });

    chunks.push(...declarationChunks);

    // Create dependencies
    const nameToChunk = new Map();
    declarationChunks.forEach((c) => nameToChunk.set(c.name, c));

    // Add dependencies to imports
    const importChunkId = `${modulePath}._imports_`;
    chunks.forEach((chunk) => {
        if (chunk.type !== 'imports' && chunk.type !== 'file') {
            dependencies.push({
                snippet_id: chunk.id,
                dependency_name: importChunkId,
            });
        }
    });

    // Find internal dependencies
    function findIdentifiers(node, callback) {
        ts.forEachChild(node, child => {
            if (ts.isIdentifier(child)) {
                callback(child);
            }
            findIdentifiers(child, callback); // Recurse deeper
        });
    }

    declarationChunks.forEach((currentChunk) => {
        const contentAST = ts.createSourceFile(
            'temp.ts',
            currentChunk.content,
            ts.ScriptTarget.Latest,
            true
        );

        // Helper function to recursively find identifiers
        const identifiers = [];
        function traverse(node) {
            if (ts.isIdentifier(node)) {
                identifiers.push(node.text);
            }
            ts.forEachChild(node, traverse);
        }
        traverse(contentAST);

        // Track unique identifier references
        const uniqueIdentifiers = new Set(identifiers);

        uniqueIdentifiers.forEach(refName => {
            const refChunk = nameToChunk.get(refName);
            if (refChunk && refChunk.id !== currentChunk.id) {
                dependencies.push({
                    snippet_id: currentChunk.id,
                    dependency_name: refChunk.id,
                });
            }
        });
    });

    // Remove duplicate dependencies
    const uniqueDeps = Array.from(
        new Set(dependencies.map((d) => JSON.stringify(d)))
    ).map((d) => JSON.parse(d));

    return {
        chunks: chunks.map((c) => ({
            ...c,
            content: c.content.replace(/\r?\n/g, '\\n'), // Escape newlines
        })),
        dependencies: uniqueDeps,
    };
}

// CLI entry point
if (require.main === module) {
    const filePath = process.argv[2];
    if (!filePath) {
        console.error('Usage: node parser.js <file.js>');
        process.exit(1);
    }

    parseFile(filePath)
        .then((result) => console.log(JSON.stringify(result, null, 2)))
        .catch((err) => {
            console.error('Parsing failed:', err);
            process.exit(1);
        });
}