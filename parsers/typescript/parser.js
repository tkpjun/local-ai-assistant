const fs = require('fs');
const path = require('path');
const ts = require('typescript');

// Helper to convert paths to dot notation
function convertPathToDotNotation(filePath) {
    return path
        .dirname(filePath)
        .split(path.sep)
        .join('.') + '.' + path.basename(filePath, path.extname(filePath));
}

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

function extractImports(sourceFile) {
    const imports = [];
    const importNodes = sourceFile.statements.filter(
        (n) => n.kind === ts.SyntaxKind.ImportDeclaration
    );

    importNodes.forEach((node) => {
        const moduleSpecifier = node.moduleSpecifier.text;
        const modulePath = convertPathToDotNotation(moduleSpecifier);

        // Handle default imports
        if (node.importClause?.name) {
            const name = node.importClause.name.text;
            imports.push({
                name: name,
                module: modulePath,
                type: 'default',
            });
        }

        // Handle named imports
        if (node.importClause?.namedBindings) {
            const namedImports = node.importClause.namedBindings.elements.map((element) => ({
                name: element.name.text,
                as: element.propertyName?.text || element.name.text,
            }));

            namedImports.forEach((imp) => {
                imports.push({
                    name: imp.as,
                    originalName: imp.name,
                    module: modulePath,
                    type: 'named',
                });
            });
        }

        // Handle namespace imports (import * as ...)
        if (ts.isImportDeclaration(node) && node.importClause?.name) {
            const name = node.importClause.name.text;
            imports.push({
                name: name,
                module: modulePath,
                type: 'namespace',
            });
        }
    });

    return imports;
}

function parseFile(filePath) {
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
    const imports = extractImports(sourceFile);

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
    declarationChunks.forEach((currentChunk) => {
        const contentAST = ts.createSourceFile(
            'temp.ts',
            currentChunk.content,
            ts.ScriptTarget.Latest,
            true
        );

        const identifiers = new Set();

        // Recursively collect all identifiers in the AST
        function collectIdentifiers(node) {
            if (ts.isIdentifier(node)) {
                identifiers.add(node.text);
            }
            ts.forEachChild(node, collectIdentifiers);
        }

        collectIdentifiers(contentAST);

        // Check for local dependencies
        identifiers.forEach((refName) => {
            const refChunk = nameToChunk.get(refName);
            if (refChunk && refChunk.id !== currentChunk.id) {
                dependencies.push({
                    snippet_id: currentChunk.id,
                    dependency_name: refChunk.id,
                });
            }
        });

        // Check for imported dependencies
        imports.forEach((imp) => {
            if (identifiers.has(imp.name)) {
                let depName;
                if (imp.type === 'named') {
                    depName = `${imp.module}.${imp.originalName}`;
                } else {
                    depName = `${imp.module}.${imp.name}`;
                }
                dependencies.push({
                    snippet_id: currentChunk.id,
                    dependency_name: depName,
                });
            }
        });
    });

    // Remove duplicates
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

    const result = parseFile(filePath);
    console.log(JSON.stringify(result, null, 2));
}